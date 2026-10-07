# Shared Yahoo market data

Read `README.md` before changing this package. It owns pure native daily OHLC
validation and local indicator calculations. Imports and constructors perform
no IO. Do not add provider calls, credentials, scheduler work or Discord paths.
Consumers retain source snapshots in an explicit shared cache and supply their
own verified calendars, completed-session and cutoff checks.

Tests use synthetic data only. Run the package suite and repository integration
checks after public interface changes.
