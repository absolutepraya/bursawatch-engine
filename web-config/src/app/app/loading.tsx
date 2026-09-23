export default function AppLoading() {
  return (
    <div className="page-wrap" aria-live="polite" aria-busy="true">
      <div className="loading-line loading-line-short" />
      <div className="loading-line loading-line-title" />
      <div className="loading-panel">
        <div className="loading-line" />
        <div className="loading-line" />
        <div className="loading-line loading-line-short" />
      </div>
      <span className="sr-only">Loading workspace</span>
    </div>
  );
}
