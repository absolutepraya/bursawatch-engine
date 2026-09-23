import Link from "next/link";

/** Approved Signal Fold. Preserve the source inlets and open fold gaps. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 96 96" fill="none" aria-hidden="true" focusable="false">
      <g fill="currentColor" transform="translate(-2 -2)">
        <path d="M14 10H46C66 10 79 20 79 35C79 44 74 50 65 54L51 46C60 43 65 40 65 35C65 28 58 24 46 24H14V10Z" />
        <path d="M14 33H35L74 56C82 61 86 67 86 74C86 84 73 90 51 90H14V76H50C64 76 71 74 71 70C71 67 66 64 60 60L14 33Z" />
        <path d="M14 54H31L53 67H14V54Z" />
      </g>
    </svg>
  );
}

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link className="brand" href={compact ? "/app/insights" : "/"} aria-label="Bursawatch home">
      <BrandMark className="brand-mark" />
      <span className="brand-word">Bursawatch</span>
    </Link>
  );
}
