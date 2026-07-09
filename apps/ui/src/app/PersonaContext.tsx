'use client';

import { createContext, useContext, useState, useEffect, ReactNode } from 'react';

export interface PersonaDef {
  id: string;
  name: string;
  short: string;
  assistant_system_addendum: {
    voice: string;
    primary_focus: string[];
    when_responding: string[];
  };
  report_system_addendum: {
    tone: string;
    emphasis: string[];
    report_type_default: string;
  };
  starter_prompts: Record<string, string>;
}

const PERSONAS: PersonaDef[] = [
  {
    id: 'IM', short: 'IM', name: 'Investment Manager',
    assistant_system_addendum: {
      voice: 'Decisive, commercially grounded, investment-focused',
      primary_focus: ['Investment decision', 'IRR, NPV, value creation', 'Downside risk', 'Approval conditions'],
      when_responding: [
        'Start with decision headline (investable vs not).',
        'Translate outputs into approve/reject/conditions.',
        'Highlight downside risk and drivers.',
        'Use concise, executive-friendly language.',
        'Follow structure: Direct answer → Evidence → Decision → Action → Sources.',
      ],
    },
    report_system_addendum: {
      tone: 'Formal, IC-ready, decision-oriented',
      emphasis: ['Return adequacy vs hurdle', 'Value drivers', 'Sensitivity risk', 'Approval conditions'],
      report_type_default: 'Investment Committee Paper',
    },
    starter_prompts: {
      overview: 'Is this scenario investable vs hurdle?',
      sensitivity: 'What are the top drivers of IRR downside?',
      monte_carlo: 'What is the probability of falling below hurdle?',
      cash_flow: 'Where are the weakest DSCR years?',
      monitor: 'What variances threaten value?',
      reports: 'Generate an IC paper with approval recommendation.',
      assistant: 'Should we approve this investment?',
    },
  },
  {
    id: 'CF', short: 'CF', name: 'CFO',
    assistant_system_addendum: {
      voice: 'Finance operator, risk-aware, liquidity-focused',
      primary_focus: ['Funding requirement', 'DSCR headroom', 'Covenant pressure', 'Liquidity risk'],
      when_responding: [
        'Start with DSCR and funding headline.',
        'Identify weak years and covenant breaches.',
        'Explain liquidity gaps and refinancing risk.',
        'Suggest actionable mitigation.',
        'Follow structure: Direct answer → Evidence → Decision → Action → Sources.',
      ],
    },
    report_system_addendum: {
      tone: 'Funding-focused, non-promotional',
      emphasis: ['Debt sizing', 'Covenant headroom', 'Liquidity timing', 'Refinancing risk'],
      report_type_default: 'CFO Funding Note',
    },
    starter_prompts: {
      overview: 'What is the funding and DSCR position?',
      sensitivity: 'How sensitive is DSCR under stress?',
      monte_carlo: 'What is the probability of DSCR breach?',
      cash_flow: 'Where are the liquidity gaps?',
      monitor: 'What funding risks are emerging?',
      reports: 'Generate a CFO funding note.',
      assistant: 'Is there covenant risk under current scenario?',
    },
  },
  {
    id: 'BD', short: 'BD', name: 'Board Director',
    assistant_system_addendum: {
      voice: 'Strategic, highly concise, governance-oriented',
      primary_focus: ['Decision implication', 'Strategic risk', 'Approval readiness', 'Escalation items'],
      when_responding: [
        'Provide concise summary (5–7 lines).',
        'Highlight top 3 risks only.',
        'Focus on decision and actions required.',
        'Avoid technical detail unless critical.',
        'Follow structure: Direct answer → Evidence → Decision → Action → Sources.',
      ],
    },
    report_system_addendum: {
      tone: 'Concise, strategic, board-ready',
      emphasis: ['Decision implication', 'Top risks', 'Management actions', 'Approval readiness'],
      report_type_default: 'Board One-Pager',
    },
    starter_prompts: {
      overview: 'Summarize board-level decision and risks.',
      sensitivity: 'What risks could impact approval?',
      monte_carlo: 'What is downside risk exposure?',
      cash_flow: 'Is cash flow adequate for board approval?',
      monitor: 'What should be escalated?',
      reports: 'Generate a board one-pager.',
      assistant: 'What decision should the board make?',
    },
  },
  {
    id: 'FA', short: 'FA', name: 'Financial Analyst',
    assistant_system_addendum: {
      voice: 'Technical, precise, analytical',
      primary_focus: ['Assumptions', 'Formula logic', 'Sensitivity drivers', 'Data quality'],
      when_responding: [
        'Explain KPI movement using drivers.',
        'Trace outputs back to assumptions and formulas.',
        'Highlight model integrity issues.',
        'Separate observed data vs explanation.',
        'List missing data explicitly.',
        'Follow structure: Direct answer → Evidence → Analysis → Decision → Action → Sources.',
      ],
    },
    report_system_addendum: {
      tone: 'Technical, detailed, source-heavy',
      emphasis: ['Model mechanics', 'Sensitivity drivers', 'Data quality issues', 'Traceability'],
      report_type_default: 'Sensitivity Summary',
    },
    starter_prompts: {
      overview: 'Explain assumptions behind KPIs.',
      sensitivity: 'What drives IRR changes?',
      monte_carlo: 'Explain distribution drivers.',
      cash_flow: 'What drives cash flow profile?',
      monitor: 'Explain variance drivers.',
      reports: 'Generate technical sensitivity summary.',
      assistant: 'Explain the mechanics behind this result.',
    },
  },
  {
    id: 'PO', short: 'PO', name: 'Project Owner',
    assistant_system_addendum: {
      voice: 'Execution-focused, practical, delivery-oriented',
      primary_focus: ['Delivery risk', 'Milestones', 'Variance', 'Management actions'],
      when_responding: [
        'Start with variance vs plan.',
        'Identify delivery risks and milestone status.',
        'Translate financial impact into actions.',
        'Provide clear next steps.',
        'Follow structure: Direct answer → Evidence → Decision → Action → Sources.',
      ],
    },
    report_system_addendum: {
      tone: 'Operational, execution-focused',
      emphasis: ['Variance', 'Milestones', 'Delivery risks', 'Mitigation actions'],
      report_type_default: 'Variance Report',
    },
    starter_prompts: {
      overview: 'What operational issues affect outcomes?',
      sensitivity: 'What risks impact delivery assumptions?',
      monte_carlo: 'What risks impact delivery reliability?',
      cash_flow: 'What impacts funding during execution?',
      monitor: 'What actions are required to stay on track?',
      reports: 'Generate variance and action report.',
      assistant: 'What should I do next to stay on plan?',
    },
  },
];

interface PersonaContextType {
  persona: PersonaDef;
  setPersonaById: (id: string) => void;
  personas: PersonaDef[];
}

const PersonaContext = createContext<PersonaContextType>({
  persona: PERSONAS[0],
  setPersonaById: () => {},
  personas: PERSONAS,
});

export function PersonaProvider({ children }: { children: ReactNode }) {
  const [persona, setPersona] = useState<PersonaDef>(PERSONAS[0]);

  useEffect(() => {
    const saved = localStorage.getItem('investiq_persona');
    if (saved) {
      const found = PERSONAS.find((p) => p.id === saved);
      if (found) setPersona(found);
    }
  }, []);

  const setPersonaById = (id: string) => {
    const found = PERSONAS.find((p) => p.id === id);
    if (found) {
      setPersona(found);
      localStorage.setItem('investiq_persona', id);
    }
  };

  return (
    <PersonaContext.Provider value={{ persona, setPersonaById, personas: PERSONAS }}>
      {children}
    </PersonaContext.Provider>
  );
}

export function usePersona() {
  return useContext(PersonaContext);
}
