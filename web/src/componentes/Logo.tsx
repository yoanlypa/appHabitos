/** La marca: una hoja de parte con su visto bueno. La misma que el icono. */
export function Logo({ lado = 26 }: { lado?: number }) {
  return (
    <svg className="logo" width={lado} height={lado} viewBox="0 0 48 48" aria-hidden="true">
      <rect width="48" height="48" rx="12" fill="#4f46e5" />
      <path
        d="M14 25.5l6.5 6.5L34.5 17"
        fill="none"
        stroke="#fff"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
