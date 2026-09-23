"use client";

import {
  ArrowRight,
  Check,
  FileText,
  Hash,
  MessageSquare,
  Pause,
  Play,
  RotateCcw,
  SlidersHorizontal,
} from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { BrandMark } from "@/components/brand";

const stages = [
  {
    title: "Choose sources",
    heading: "Start with the voices you trust.",
    description:
      "Research channels, market commentary and Sectors data. Bring them into the same routine without losing where each update came from.",
  },
  {
    title: "Set your rules",
    heading: "Less noise. More of what matters.",
    description:
      "Choose the topics, companies and reading style you care about. Keep an original source link with every summary.",
  },
  {
    title: "Read your brief",
    heading: "A clear update. In your channel.",
    description:
      "See the source, the context and what to review next. This example shows a Discord brief, with facts kept separate from interpretation.",
  },
];

const sources = [
  { title: "Research channel", detail: "Telegram · Securities research", Icon: MessageSquare },
  { title: "Market commentary", detail: "X · Public account", Icon: Hash },
  { title: "Company data", detail: "Sectors · Fundamentals", Icon: FileText },
];

function subscribeToMotion(callback: () => void) {
  const query = window.matchMedia("(prefers-reduced-motion: reduce)");
  query.addEventListener("change", callback);
  return () => query.removeEventListener("change", callback);
}

function getReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function WorkflowWalkthrough() {
  const [stage, setStage] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [paused, setPaused] = useState(false);
  const [animated, setAnimated] = useState(false);
  const sceneRef = useRef<HTMLDivElement>(null);
  const interacted = useRef(false);
  const reducedMotion = useSyncExternalStore(subscribeToMotion, getReducedMotion, () => true);
  const isPlaying = playing && !reducedMotion;

  useEffect(() => {
    if (reducedMotion || interacted.current || !sceneRef.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (
          entry.isIntersecting &&
          entry.intersectionRatio >= 0.5 &&
          !document.hidden &&
          !interacted.current
        ) {
          interacted.current = true;
          setAnimated(true);
          setPlaying(true);
          observer.disconnect();
        }
      },
      { threshold: 0.5 },
    );
    observer.observe(sceneRef.current);
    return () => observer.disconnect();
  }, [reducedMotion]);

  useEffect(() => {
    if (!isPlaying) return;
    const timer = window.setTimeout(() => {
      if (stage === stages.length - 1) {
        setPlaying(false);
        setPaused(false);
      } else setStage(stage + 1);
    }, 6500);
    return () => window.clearTimeout(timer);
  }, [isPlaying, stage]);

  useEffect(() => {
    const pauseWhenHidden = () => {
      if (document.hidden && playing) {
        setPlaying(false);
        setPaused(true);
      }
    };
    const pauseOnReducedMotion = () => {
      if (getReducedMotion()) setPlaying(false);
    };
    document.addEventListener("visibilitychange", pauseWhenHidden);
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    query.addEventListener("change", pauseOnReducedMotion);
    return () => {
      document.removeEventListener("visibilitychange", pauseWhenHidden);
      query.removeEventListener("change", pauseOnReducedMotion);
    };
  }, [playing]);

  function chooseStage(index: number) {
    interacted.current = true;
    setAnimated(false);
    setPlaying(false);
    setPaused(false);
    setStage(index);
  }

  function togglePlayback() {
    interacted.current = true;
    setAnimated(true);
    if (!isPlaying && !paused && stage === stages.length - 1) setStage(0);
    setPaused(isPlaying);
    setPlaying(!isPlaying);
  }

  return (
    <section className="workflow-demo" id="how-it-works" aria-label="How Bursawatch works">
      <div className="demo-toolbar">
        <h2>From source to brief</h2>
        <span className="example-label">Illustrative walkthrough</span>
        {!reducedMotion && (
          <button type="button" className="button secondary" onClick={togglePlayback}>
            {isPlaying ? (
              <Pause size={16} aria-hidden="true" />
            ) : stage === 2 && !paused ? (
              <RotateCcw size={16} aria-hidden="true" />
            ) : (
              <Play size={16} aria-hidden="true" />
            )}
            {isPlaying
              ? "Pause walkthrough"
              : paused
                ? "Resume walkthrough"
                : stage === 2
                  ? "Replay walkthrough"
                  : "Play walkthrough"}
          </button>
        )}
      </div>
      <div className="demo-stages" role="group" aria-label="Walkthrough stages">
        {stages.map((item, index) => (
          <button
            type="button"
            key={item.title}
            aria-pressed={stage === index}
            onClick={() => chooseStage(index)}
            aria-controls="walkthrough-scene"
          >
            <span className="demo-stage-number" aria-hidden="true">
              {index + 1}
            </span>
            <span>{item.title}</span>
            {index < 2 && <ArrowRight size={16} className="demo-stage-arrow" aria-hidden="true" />}
          </button>
        ))}
      </div>
      <div className="demo-body">
        <div
          className="demo-scene"
          id="walkthrough-scene"
          ref={sceneRef}
          data-stage={stage}
          data-animated={animated && !reducedMotion}
          data-playing={isPlaying}
        >
          <div className="demo-scene-content" key={stage}>
            {stage === 0 && (
              <div className="demo-source-list">
                <div className="demo-window-title">
                  <span>Example sources</span>
                  <span>3 sources</span>
                </div>
                {sources.map(({ title, detail, Icon }) => (
                  <div className="demo-source-row" key={title}>
                    <span className="demo-source-icon">
                      <Icon size={20} aria-hidden="true" />
                    </span>
                    <div>
                      <strong>{title}</strong>
                      <span>{detail}</span>
                    </div>
                    <Check size={17} aria-label="Selected" />
                  </div>
                ))}
                <div className="demo-source-note">
                  <BrandMark className="brand-mark" />
                  <span>
                    A BBRI research note comes in.
                    <br />
                    <strong>Your rules decide what belongs.</strong>
                  </span>
                </div>
                <div className="demo-arrival demo-event">
                  <MessageSquare size={18} aria-hidden="true" />
                  <div>
                    <strong>New research note</strong>
                    <span>BBRI · Banking outlook</span>
                  </div>
                  <span className="demo-chip">Received</span>
                </div>
              </div>
            )}
            {stage === 1 && (
              <div className="demo-rule-sheet">
                <div className="demo-window-title">
                  <span>Your research brief</span>
                  <SlidersHorizontal size={18} aria-hidden="true" />
                </div>
                <dl>
                  <div>
                    <dt>Focus</dt>
                    <dd>
                      <span className="demo-chip">IDX stocks</span>
                      <span className="demo-chip">Company results</span>
                    </dd>
                  </div>
                  <div>
                    <dt>Watchlist</dt>
                    <dd>BBRI · BMRI · TLKM</dd>
                  </div>
                  <div>
                    <dt>Reading style</dt>
                    <dd>Concise, with source links</dd>
                  </div>
                  <div>
                    <dt>Destination</dt>
                    <dd>Discord · #market-brief</dd>
                  </div>
                </dl>
                <p className="demo-rule-note">
                  <Check size={16} aria-hidden="true" /> BBRI matches your watchlist.
                </p>
                <div className="demo-filter-results">
                  <div className="demo-event">
                    <Check size={16} aria-hidden="true" />
                    <span>BBRI research note</span>
                    <strong>Keep</strong>
                  </div>
                  <div className="demo-event">
                    <span aria-hidden="true">−</span>
                    <span>Unrelated market chatter</span>
                    <strong>Skip</strong>
                  </div>
                </div>
              </div>
            )}
            {stage === 2 && (
              <div className="demo-message">
                <div className="demo-window-title">
                  <span>
                    <Hash size={17} aria-hidden="true" /> market-brief
                  </span>
                  <span>Discord preview</span>
                </div>
                <div className="demo-message-author">
                  <BrandMark className="brand-mark" />
                  <strong>Bursawatch</strong>
                  <span>Example</span>
                </div>
                <div className="demo-message-copy">
                  <h3>BBRI: a new research note.</h3>
                  <p>
                    <strong>Source view</strong>
                    <br />
                    The research channel shares its outlook for BBRI. This is the author’s view, not
                    a company announcement.
                  </p>
                  <p>
                    <strong>What to review</strong>
                    <br />
                    Compare the thesis with company results. A positive view is not a guarantee of
                    returns.
                  </p>
                  <div className="demo-citations">
                    <FileText size={15} aria-hidden="true" /> Original note <span>·</span> Sectors
                    company data
                  </div>
                </div>
                <div className="demo-delivery demo-event">
                  <Check size={16} aria-hidden="true" />
                  Ready for #market-brief <span>Preview only</span>
                </div>
              </div>
            )}
          </div>
        </div>
        <div className="demo-explanation">
          <div aria-live="polite" aria-atomic="true">
            <h3>{stages[stage].heading}</h3>
            <p>{stages[stage].description}</p>
          </div>
          <div className="demo-controls">
            <p role="status">
              {reducedMotion
                ? "Choose a step to explore. Motion is off."
                : isPlaying
                  ? `Step ${stage + 1} of 3 · Playing`
                  : paused
                    ? `Step ${stage + 1} of 3 · Paused`
                    : "Play the sequence, or choose any step."}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
