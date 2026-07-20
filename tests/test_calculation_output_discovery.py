from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
import pytest
from sqlalchemy import select

from apps.api.app.calculation_rules.models import WorkbookFormulaCellRecord
from apps.api.app.calculation_rules.service import CalculationRuleExtractionService
from apps.api.app.database import Base
from apps.api.app.model_extraction_models import (
    CanonicalOutput,
    FinancialSeriesValue,
    ModelVersion,
)
from apps.api.app.model_extraction_read_service import ModelExtractionReadService
from apps.api.app.model_extraction_repository import WorkbookVersionRepository
from apps.api.app.model_extraction_types import FinancialEntityIdFactory, new_uuid
from apps.api.app.workbook_storage import DatabaseWorkbookStorage
from tests.calculation_rule_test_support import create_materialized_rule_model
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    sqlite_file_url,
)


@pytest.fixture
def discovery_context(tmp_path: Path):
    engine, session_factory = create_sqlite_session_factory(
        sqlite_file_url(tmp_path / "output-discovery.db")
    )
    Base.metadata.create_all(engine)
    session = session_factory()
    storage, workbook, model, _parameter, series, _series_value = (
        create_materialized_rule_model(session)
    )
    series.business_role = "revenue"
    id_factory = FinancialEntityIdFactory(model.id)
    output_id = id_factory.output_id("Calc", "B1")
    session.add(
        FinancialSeriesValue(
            id=id_factory.value_id(series.id, 1),
            financial_series_id=series.id,
            period_index=1,
            raw_period_label_json=2027,
            display_period_label="2027",
            period_type="annual",
            year=2027,
            is_forecast=True,
            value_json=None,
            period_source_sheet="Calc",
            period_source_cell="A2",
            value_source_sheet="Calc",
            value_source_cell="B8",
            exact_formula="=IF(TRUE,B2,1/0)",
            formula_status="formula_no_cache",
            cached_value_available=False,
            cached_value_freshness="missing",
            number_format="General",
            data_type="f",
        )
    )
    session.commit()

    read_service = ModelExtractionReadService(session, storage)
    CalculationRuleExtractionService(session, read_service).extract_and_execute(
        model.id,
        workbook.id,
    )
    try:
        yield session, read_service, model, series, output_id
    finally:
        session.close()
        engine.dispose()


def test_discovery_maps_scalar_output_uuid_to_exact_formula_cell(
    discovery_context,
) -> None:
    session, read_service, model, _series, output_id = discovery_context
    expected_formula_cell_id = session.scalar(
        select(WorkbookFormulaCellRecord.id).where(
            WorkbookFormulaCellRecord.workbook_version_id
            == model.workbook_version_id,
            WorkbookFormulaCellRecord.sheet_name == "Calc",
            WorkbookFormulaCellRecord.cell_address == "B1",
        )
    )

    definitions = read_service.list_calculation_outputs(model.id)

    scalar = next(item for item in definitions if item.output_id == output_id)
    assert scalar.entity_kind == "scalar"
    assert scalar.business_role == "total_project_cost"
    assert scalar.source.formula_cell_id == expected_formula_cell_id
    assert scalar.mapping_status == "mapped"
    assert scalar.support_status == "supported"


def test_discovery_maps_each_series_period_to_exact_formula_cell(
    discovery_context,
) -> None:
    session, read_service, model, series, _output_id = discovery_context
    expected_formula_cells = {
        row.cell_address: row.id
        for row in session.scalars(
            select(WorkbookFormulaCellRecord).where(
            WorkbookFormulaCellRecord.workbook_version_id
            == model.workbook_version_id,
            WorkbookFormulaCellRecord.sheet_name == "Calc",
            WorkbookFormulaCellRecord.cell_address.in_(["B2", "B8"]),
        )
        ).all()
    }

    definitions = read_service.list_calculation_outputs(model.id)

    discovered_series = next(
        item for item in definitions if item.output_id == series.id
    )
    assert discovered_series.entity_kind == "series"
    assert discovered_series.business_role == "revenue"
    assert len(discovered_series.points) == 2
    assert [point.period for point in discovered_series.points] == ["2026", "2027"]
    assert [point.formula_cell_id for point in discovered_series.points] == [
        expected_formula_cells["B2"],
        expected_formula_cells["B8"],
    ]
    assert {point.support_status for point in discovered_series.points} == {
        "supported"
    }
    assert discovered_series.mapping_status == "mapped"
    assert discovered_series.support_status == "supported"


def test_same_business_role_uses_model_specific_source_cells(
    discovery_context,
) -> None:
    session, read_service, first_model, _series, _output_id = discovery_context
    workbook = Workbook()
    inputs = workbook.active
    inputs.title = "Inputs"
    inputs["A1"] = 4
    inputs["A2"] = 6
    returns = workbook.create_sheet("Returns")
    returns["D5"] = "=SUM(Inputs!A1:A2)"
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()

    second_workbook = WorkbookVersionRepository(
        session,
        DatabaseWorkbookStorage(session),
    ).get_or_create(buffer.getvalue(), "alternate-model.xlsx")
    second_model = ModelVersion(
        id=new_uuid(),
        workbook_version_id=second_workbook.id,
        upload_filename="alternate-model.xlsx",
        status="materialized",
        validation_status="validated",
        submitted=True,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    second_output_id = FinancialEntityIdFactory(second_model.id).output_id(
        "Returns",
        "D5",
    )
    session.add_all(
        [
            second_model,
            CanonicalOutput(
                id=second_output_id,
                model_version_id=second_model.id,
                entity_kind="canonical_output",
                label="Total project cost",
                business_role="total_project_cost",
                submitted_role="formula_output",
                validated_role="formula_output",
                source_sheet="Returns",
                source_cell="D5",
                exact_formula="=SUM(Inputs!A1:A2)",
                formula_status="formula_no_cache",
                source_validation_status="validated",
                role_validation_status="validated",
                validation_status="validated",
            ),
        ]
    )
    session.commit()
    CalculationRuleExtractionService(session, read_service).extract_and_execute(
        second_model.id,
        second_workbook.id,
    )

    first = next(
        item
        for item in read_service.list_calculation_outputs(first_model.id)
        if item.business_role == "total_project_cost"
    )
    second = next(
        item
        for item in read_service.list_calculation_outputs(second_model.id)
        if item.business_role == "total_project_cost"
    )

    assert first.output_id != second.output_id
    assert (first.source.sheet_name, first.source.cell_address) == ("Calc", "B1")
    assert (second.source.sheet_name, second.source.cell_address) == (
        "Returns",
        "D5",
    )
    assert first.source.formula_cell_id != second.source.formula_cell_id
