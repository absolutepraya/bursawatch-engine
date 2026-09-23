"use client";

import {
  ArrowRight,
  Check,
  ChevronDown,
  Pause,
  Play,
  RotateCcw,
  SlidersHorizontal,
} from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { BrandMark } from "@/components/brand";
import {
  marketExamples,
  marketTimes,
  changeFromOpen,
  formatMove,
  formatPrice,
} from "@/lib/market-example";

const story = ["Follow the move", "Check your rule", "Keep the context"];
const x = (index: number) => 16 + (index / (marketTimes.length - 1)) * 584;
const y = (change: number) => 244 - ((change + 1) / 7) * 224;

function subscribeMotion(callback: () => void) {
  const query = window.matchMedia("(prefers-reduced-motion: reduce)");
  query.addEventListener("change", callback);
  return () => query.removeEventListener("change", callback);
}

export function MarketPreview({ configureUrl }: { configureUrl: string }) {
  const [selected, setSelected] = useState(0);
  const [threshold, setThreshold] = useState(3);
  const [point, setPoint] = useState(marketTimes.length - 1);
  const [stage, setStage] = useState(2);
  const [playing, setPlaying] = useState(false);
  const [paused, setPaused] = useState(false);
  const [animated, setAnimated] = useState(false);
  const [replay, setReplay] = useState(0);
  const interacted = useRef(false);
  const previewRef = useRef<HTMLElement>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const reducedMotion = useSyncExternalStore(
    subscribeMotion,
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => true,
  );
  const isPlaying = playing && !reducedMotion;
  const item = marketExamples[selected];
  const changes = item.prices.map((price) => changeFromOpen(price, item.prices[0]));
  const finalChange = changes.at(-1)!;
  const matched = finalChange >= threshold;
  const path = changes
    .map((change, index) => `${index === 0 ? "M" : "L"}${x(index)},${y(change)}`)
    .join(" ");
  const showRule = stage >= 1;

  useEffect(() => {
    if (reducedMotion || !chartRef.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (
          entry.isIntersecting &&
          entry.intersectionRatio >= 0.55 &&
          !document.hidden &&
          !interacted.current
        ) {
          interacted.current = true;
          setStage(0);
          setAnimated(true);
          setPlaying(true);
          observer.disconnect();
        }
      },
      { threshold: [0, 0.55] },
    );
    observer.observe(chartRef.current);
    return () => observer.disconnect();
  }, [reducedMotion]);

  useEffect(() => {
    if (!isPlaying || !previewRef.current) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) {
        setPlaying(false);
        setPaused(true);
      }
    });
    observer.observe(previewRef.current);
    return () => observer.disconnect();
  }, [isPlaying]);

  useEffect(() => {
    if (!isPlaying) return;
    const timer = window.setTimeout(() => {
      if (stage === 2) {
        setPlaying(false);
        setPaused(false);
      } else setStage(stage + 1);
    }, 3200);
    return () => window.clearTimeout(timer);
  }, [isPlaying, stage]);

  useEffect(() => {
    const stop = () => {
      if (document.hidden) {
        setPlaying(false);
        if (playing) setPaused(true);
      }
    };
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const stopMotion = () => {
      if (motion.matches) {
        setPlaying(false);
        setPaused(false);
        setAnimated(false);
        setStage(2);
      }
    };
    document.addEventListener("visibilitychange", stop);
    motion.addEventListener("change", stopMotion);
    return () => {
      document.removeEventListener("visibilitychange", stop);
      motion.removeEventListener("change", stopMotion);
    };
  }, [playing]);

  function takeControl() {
    interacted.current = true;
    setPlaying(false);
    setPaused(false);
    setAnimated(false);
    setStage(2);
  }

  function togglePlayback() {
    interacted.current = true;
    if (isPlaying) {
      setPlaying(false);
      setPaused(true);
    } else {
      if (!paused) {
        setStage(0);
        setReplay(replay + 1);
      }
      setPoint(marketTimes.length - 1);
      setAnimated(true);
      setPlaying(true);
      setPaused(false);
    }
  }

  return (
    <section
      ref={previewRef}
      className="market-preview"
      aria-label="Interactive example watch"
      data-stage={stage}
      data-playing={isPlaying}
      data-animated={animated && !reducedMotion}
    >
      <header className="preview-toolbar">
        <span className="preview-title">
          <BrandMark className="brand-mark" /> Your market watch
        </span>
        <span className="example-label">Illustrative prices · not live</span>
      </header>
      <div className="preview-workspace">
        <div className="price-panel">
          <div className="price-heading">
            <div>
              <h2>
                {item.symbol} <span>{item.name}</span>
              </h2>
              <div className="price-value">
                {formatPrice(item.prices[point])}{" "}
                <span className="stock-change" data-negative={changes[point] < 0}>
                  {formatMove(changes[point])}
                </span>
              </div>
            </div>
            <span className="session-label">
              One sample session<span>Change from open</span>
            </span>
          </div>
          <div className="price-chart" ref={chartRef}>
            <div className="chart-plot">
              <div className="chart-axis" aria-hidden="true">
                {[6, 4, 2, 0].map((value) => (
                  <span key={value} style={{ top: `${(y(value) / 272) * 100}%` }}>
                    {value > 0 ? "+" : ""}
                    {value}%
                  </span>
                ))}
              </div>
              <svg
                viewBox="0 0 616 272"
                preserveAspectRatio="none"
                role="img"
                aria-label={`${item.symbol} illustrative session: ${formatPrice(item.prices[0])} at open to ${formatPrice(item.prices.at(-1)!)} at 15:30 WIB, ${formatMove(finalChange)}. ${showRule ? `Dashed line marks the ${threshold}% alert rule.` : "Select Check your rule to show the alert threshold."}`}
              >
                {[0, 2, 4, 6].map((value) => (
                  <line
                    key={value}
                    className="chart-gridline"
                    x1="16"
                    x2="600"
                    y1={y(value)}
                    y2={y(value)}
                  />
                ))}
                <path
                  key={`area-${selected}-${replay}`}
                  className="chart-area"
                  d={`${path} L600,${y(0)} L16,${y(0)} Z`}
                />
                <path
                  key={`${selected}-${replay}`}
                  className="chart-price-line"
                  d={path}
                  pathLength="1"
                />
                <g className="chart-rule" data-visible={showRule}>
                  <line x1="16" x2="600" y1={y(threshold)} y2={y(threshold)} />
                </g>
                <line className="chart-crosshair" x1={x(point)} x2={x(point)} y1="18" y2="248" />
                <circle className="chart-point" cx={x(point)} cy={y(changes[point])} r="5" />
              </svg>
            </div>
            <div className="chart-time-axis" aria-hidden="true">
              <span>09:00</span>
              <span>10:40</span>
              <span>13:50</span>
              <span>15:30 WIB</span>
            </div>
          </div>
          <div className="chart-inspection">
            <label htmlFor="sample-price">
              Inspect a price{" "}
              <span>
                {marketTimes[point]} WIB · {formatPrice(item.prices[point])}
              </span>
            </label>
            <input
              id="sample-price"
              type="range"
              min="0"
              max={marketTimes.length - 1}
              value={point}
              aria-valuetext={`${marketTimes[point]} WIB, ${formatPrice(item.prices[point])}, ${formatMove(changes[point])} from open`}
              onChange={(event) => {
                takeControl();
                setPoint(Number(event.target.value));
              }}
            />
          </div>
          <div className="chart-legend">
            <span>
              <i /> Sample price
            </span>
            <span>
              <i /> Alert at +{threshold}%
            </span>
          </div>
          <p className="chart-spacing-note">Sample observations, equally spaced.</p>
        </div>
        <aside className="watch-panel" aria-label="Example watch controls">
          <div className="watch-panel-heading">
            <span>Your watchlist</span>
            <span>3 stocks</span>
          </div>
          <div className="ticker-tabs" role="group" aria-label="Choose an example stock">
            {marketExamples.map((stock, index) => (
              <button
                type="button"
                key={stock.symbol}
                aria-pressed={selected === index}
                onClick={() => {
                  takeControl();
                  setSelected(index);
                  setPoint(marketTimes.length - 1);
                }}
              >
                <span>
                  <strong>{stock.symbol}</strong>
                  <small>{stock.shortName}</small>
                </span>
                <svg viewBox="0 0 74 28" aria-hidden="true">
                  <polyline
                    points={stock.prices
                      .map(
                        (price, priceIndex) =>
                          `${2 + (priceIndex / (stock.prices.length - 1)) * 70},${25 - changeFromOpen(price, stock.prices[0]) * 4}`,
                      )
                      .join(" ")}
                  />
                </svg>
                <span className="stock-change">
                  {formatMove(changeFromOpen(stock.prices.at(-1)!, stock.prices[0]))}
                </span>
              </button>
            ))}
          </div>
          <div className="preview-rule" data-active={showRule}>
            <div>
              <SlidersHorizontal size={17} aria-hidden="true" />
              <strong>Your alert rule</strong>
            </div>
            <label htmlFor="alert-threshold">Daily rise at least</label>
            <select
              id="alert-threshold"
              value={threshold}
              onChange={(event) => {
                takeControl();
                setThreshold(Number(event.target.value));
              }}
            >
              <option value="2">+2%</option>
              <option value="3">+3%</option>
              <option value="5">+5%</option>
            </select>
            <p>Checked at 15:30 WIB</p>
          </div>
        </aside>
      </div>
      <div className="market-story-controls">
        <div role="group" aria-label="Price story stages">
          {story.map((title, index) => (
            <button
              type="button"
              key={title}
              aria-pressed={stage === index}
              aria-controls="price-story-result"
              onClick={() => {
                takeControl();
                setStage(index);
              }}
            >
              <span aria-hidden="true">0{index + 1}</span>
              {title}
            </button>
          ))}
        </div>
        {!reducedMotion && (
          <button type="button" className="story-playback" onClick={togglePlayback}>
            {isPlaying ? (
              <Pause size={16} aria-hidden="true" />
            ) : paused ? (
              <Play size={16} aria-hidden="true" />
            ) : (
              <RotateCcw size={16} aria-hidden="true" />
            )}
            {isPlaying ? "Pause price story" : paused ? "Resume price story" : "Replay price story"}
          </button>
        )}
      </div>
      <div className="preview-result" id="price-story-result">
        <span className="result-mark">
          <Check size={20} aria-hidden="true" />
        </span>
        <div className="result-copy" aria-live={isPlaying ? "off" : "polite"} aria-atomic="true">
          <span className="result-label">
            {stage === 0
              ? "Sample session"
              : stage === 1
                ? "Example rule"
                : matched
                  ? "Example brief"
                  : "No alert needed"}{" "}
            · {item.symbol} · 15:30 WIB
          </span>
          <h3>
            {stage === 0
              ? `Follow ${item.symbol}, one observation at a time.`
              : stage === 1
                ? `Check for a rise of at least ${threshold}%.`
                : `${item.symbol} ${matched ? `crossed the ${threshold}% threshold.` : "stayed within your threshold."}`}
          </h3>
          <p>
            {stage === 0
              ? "Inspect the sample prices with the slider. Every change is measured from this session’s opening price."
              : stage === 1
                ? `The dashed line marks your rule. Compare the final ${formatMove(finalChange)} move with a +${threshold}% threshold to see whether this check would create a brief.`
                : matched
                  ? `The sample session closed ${formatMove(finalChange)} from open. ${item.context}`
                  : `The sample session closed ${formatMove(finalChange)}, below your ${threshold}% rule. This check would stay quiet.`}
          </p>
        </div>
        <a className="text-link" href={configureUrl}>
          Configure your sources <ArrowRight size={16} aria-hidden="true" />
        </a>
      </div>
      <details
        className="chart-data"
        onToggle={(event) => {
          if (event.currentTarget.open) takeControl();
        }}
      >
        <summary>
          View sample prices <ChevronDown size={15} aria-hidden="true" />
        </summary>
        <p>
          Invented prices for this interactive example. No market connection or message is sent.
        </p>
        <table>
          <caption>{item.symbol} · illustrative session in IDR</caption>
          <thead>
            <tr>
              <th scope="col">Time (WIB)</th>
              <th scope="col">Price</th>
              <th scope="col">From open</th>
            </tr>
          </thead>
          <tbody>
            {item.prices.map((price, index) => (
              <tr key={marketTimes[index]}>
                <th scope="row">{marketTimes[index]}</th>
                <td>{formatPrice(price)}</td>
                <td>{formatMove(changes[index])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}
