const WIB_OFFSET_MS = 7 * 60 * 60 * 1000;

function isWeekend(localDate: Date) {
  const day = localDate.getUTCDay();
  return day === 0 || day === 6;
}

export function nextScheduledRun(now = new Date(), scheduleTime = "15:30", demoSeconds?: number) {
  if (demoSeconds && Number.isFinite(demoSeconds) && demoSeconds > 0) {
    return new Date(now.getTime() + demoSeconds * 1000);
  }

  const [hour, minute] = scheduleTime.split(":").map(Number);
  const localNow = new Date(now.getTime() + WIB_OFFSET_MS);
  const candidateLocal = new Date(Date.UTC(
    localNow.getUTCFullYear(),
    localNow.getUTCMonth(),
    localNow.getUTCDate(),
    hour,
    minute,
    0,
    0,
  ));

  if (candidateLocal.getTime() - WIB_OFFSET_MS <= now.getTime()) {
    candidateLocal.setUTCDate(candidateLocal.getUTCDate() + 1);
  }
  while (isWeekend(candidateLocal)) {
    candidateLocal.setUTCDate(candidateLocal.getUTCDate() + 1);
  }
  return new Date(candidateLocal.getTime() - WIB_OFFSET_MS);
}
