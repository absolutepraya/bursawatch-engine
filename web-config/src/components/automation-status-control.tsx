export function AutomationStatusControl({
  status,
}: {
  id: string;
  status: "active" | "paused" | "degraded";
}) {
  return (
    <span className="example-note">
      {status === "paused" ? "Paused sample" : "Weekday schedule"}
    </span>
  );
}
