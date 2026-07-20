export function WorkbookTransformation() {
  return (
    <figure
      className="mx-auto grid w-full max-w-[560px] grid-cols-[58px_minmax(42px,1fr)_82px_68px] items-center gap-2 py-5 sm:grid-cols-[76px_minmax(80px,1fr)_126px_98px] sm:gap-3"
      aria-label="Workbook data flowing into structured financial model blocks"
    >
      <div className="flex min-w-0 flex-col items-center">
        <svg
          viewBox="0 0 76 82"
          className="h-auto w-full max-w-[76px]"
          role="img"
          aria-label="Excel workbook"
        >
          <path
            d="M19 4h29l15 15v57H19z"
            fill="#e8edf5"
            stroke="#9aa9c4"
            strokeWidth="1.5"
          />
          <path d="M48 4v15h15" fill="#c8d2e3" stroke="#9aa9c4" strokeWidth="1.5" />
          <rect x="4" y="28" width="42" height="43" rx="3" fill="#169447" />
          <path
            d="m15 39 7 10-7.5 11h7l4-7 4.5 7h7l-8-11 7.5-10h-7l-4 6.5-4-6.5z"
            fill="white"
          />
        </svg>
        <figcaption className="mt-2 whitespace-nowrap text-[10px] font-medium text-slate-100 sm:text-xs">
          Your model
        </figcaption>
      </div>

      <svg
        viewBox="0 0 180 84"
        className="h-auto w-full overflow-visible"
        aria-hidden="true"
      >
        <path
          d="M2 20 C48 20 62 32 104 32 S145 15 178 15"
          fill="none"
          stroke="#2d5f9a"
          strokeWidth="1.5"
        />
        <path
          d="M2 42 C46 42 66 42 105 42 S146 42 178 42"
          fill="none"
          stroke="#4878b8"
          strokeWidth="1.5"
        />
        <path
          d="M2 64 C45 64 65 54 104 54 S145 69 178 69"
          fill="none"
          stroke="#2d5f9a"
          strokeWidth="1.5"
        />
        <rect
          className="extraction-scan"
          x="72"
          y="4"
          width="2"
          height="74"
          rx="1"
          fill="#e5c171"
        />
        <circle className="extraction-particle extraction-particle-one" cx="18" cy="20" r="2.5" fill="#e5c171" />
        <circle className="extraction-particle extraction-particle-two" cx="18" cy="42" r="2.5" fill="#58a6ff" />
        <circle className="extraction-particle extraction-particle-three" cx="18" cy="64" r="2.5" fill="#e5c171" />
      </svg>

      <svg
        viewBox="0 0 128 104"
        className="h-auto w-full overflow-visible"
        role="img"
        aria-label="Structured workbook table"
      >
        <rect x="2" y="3" width="124" height="98" rx="6" fill="#111c44" stroke="#7080a0" strokeWidth="1.5" />
        <path d="M2 20h124M2 44h124M2 68h124M2 84h124M28 20v81M54 20v81M80 20v81M104 20v81" stroke="#526383" strokeWidth="1" />
        <rect x="3" y="4" width="122" height="15" rx="4" fill="#1b2b65" />
        <rect x="81" y="21" width="22" height="22" fill="#a88638" opacity="0.9" />
        <rect x="55" y="45" width="24" height="22" fill="#c5a059" opacity="0.82" />
        <rect x="29" y="69" width="24" height="14" fill="#274f82" opacity="0.9" />
      </svg>

      <div className="flex min-w-0 items-center gap-1 sm:gap-2">
        <svg
          viewBox="0 0 26 54"
          className="w-4 shrink-0 text-slate-300 sm:w-5"
          aria-hidden="true"
        >
          <path d="M2 27h20M16 20l7 7-7 7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <svg
          viewBox="0 0 92 100"
          className="h-auto min-w-0 flex-1"
          role="img"
          aria-label="Financial model output blocks"
        >
          <rect x="2" y="2" width="40" height="43" rx="6" fill="#182b55" />
          <rect x="50" y="2" width="40" height="43" rx="6" fill="#182b55" />
          <rect x="2" y="53" width="40" height="43" rx="6" fill="#182b55" />
          <rect x="50" y="53" width="40" height="43" rx="6" fill="#182b55" />
          <path d="M11 34 20 24l7 5 8-13M32 16h4v4" fill="none" stroke="#90a5c8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M58 14h25v21H58zM58 21h25M66 14v21M75 14v21" fill="none" stroke="#90a5c8" strokeWidth="1.5" />
          <path d="M23 62v26M30 68c-1-4-13-5-13 2 0 8 14 4 14 12 0 7-13 6-15 2" fill="none" stroke="#90a5c8" strokeWidth="2" strokeLinecap="round" />
          <path d="M59 86V73M69 86V63M79 86V56" fill="none" stroke="#90a5c8" strokeWidth="3" strokeLinecap="round" />
        </svg>
      </div>
    </figure>
  );
}
