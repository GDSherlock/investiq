"""Server-owned persona profiles for report generation."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from .report_chat_schemas import PersonaId


@dataclass(frozen=True)
class ReportPersonaProfile:
    id: PersonaId
    name: str
    report_type: str
    primary_prompt: str
    focus: Sequence[str]
    system_addendum: str


_REPORT_PERSONAS: Mapping[PersonaId, ReportPersonaProfile] = MappingProxyType(
    {
        "IM": ReportPersonaProfile(
            id="IM",
            name="Investment Manager",
            report_type="Investment Committee Paper",
            primary_prompt="Generate an Investment Committee Paper",
            focus=(
                "Decision",
                "Returns",
                "Downside risk",
                "Approval conditions",
            ),
            system_addendum=(
                "Write a formal, decision-oriented Investment Committee Paper "
                "focused on return adequacy, value drivers, downside risk, and "
                "evidence-backed approval conditions."
            ),
        ),
        "CF": ReportPersonaProfile(
            id="CF",
            name="CFO",
            report_type="CFO Funding Note",
            primary_prompt="Generate a CFO Funding Note",
            focus=(
                "Funding",
                "Liquidity",
                "Capital structure",
                "DSCR",
                "Covenants",
            ),
            system_addendum=(
                "Write a non-promotional CFO Funding Note focused on funding "
                "requirements, liquidity timing, capital structure, DSCR, "
                "covenant headroom, and refinancing risk."
            ),
        ),
        "BD": ReportPersonaProfile(
            id="BD",
            name="Board Director",
            report_type="Board One-Pager",
            primary_prompt="Generate a Board One-Pager",
            focus=(
                "Decision headline",
                "Top risks",
                "Management actions",
            ),
            system_addendum=(
                "Write a concise, strategic Board One-Pager led by the decision "
                "headline, the most material risks, and required management actions."
            ),
        ),
        "FA": ReportPersonaProfile(
            id="FA",
            name="Financial Analyst",
            report_type="Technical Sensitivity Summary",
            primary_prompt="Generate a Technical Sensitivity Summary",
            focus=(
                "Assumptions",
                "Sensitivities",
                "Calculation logic",
                "Sources",
            ),
            system_addendum=(
                "Write a precise Technical Sensitivity Summary focused on "
                "assumptions, sensitivity drivers, calculation logic, data quality, "
                "and source traceability."
            ),
        ),
        "PO": ReportPersonaProfile(
            id="PO",
            name="Project Owner",
            report_type="Variance and Action Report",
            primary_prompt="Generate a Variance and Action Report",
            focus=(
                "Variances",
                "Milestones",
                "Risks",
                "Owners",
                "Actions",
            ),
            system_addendum=(
                "Write an execution-focused Variance and Action Report covering "
                "only evidenced variances, milestones, delivery risks, owners, and "
                "practical mitigation actions."
            ),
        ),
    }
)


def get_report_persona(persona_id: PersonaId) -> ReportPersonaProfile:
    """Return the immutable server-owned profile for a persona ID."""

    return _REPORT_PERSONAS[persona_id]
