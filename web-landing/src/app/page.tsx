import { ArrowRight, Check, Play } from "lucide-react";
import { Brand } from "@/components/brand";
import { MarketPreview } from "@/components/market-preview";
import { WorkflowWalkthrough } from "@/components/workflow-walkthrough";
import { getWorkspaceLinks } from "@/lib/workspace-links";

export default function LandingPage() {
  const workspace = getWorkspaceLinks();
  return (
    <div className="market-home">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className="market-header">
        <Brand />
        <nav aria-label="Main navigation">
          <a href="#how-it-works">How it works</a>
          <a href={workspace.discover}>Explore sample</a>
        </nav>
        <a className="button secondary" href={workspace.home}>
          Open workspace <ArrowRight size={16} aria-hidden="true" />
        </a>
      </header>
      <main id="main-content" tabIndex={-1}>
        <section className="market-hero">
          <div className="market-hero-copy">
            <h1>
              Your market. Less noise.
              <br />
              <span>A brief worth opening.</span>
            </h1>
            <p>
              Bring the sources you trust into a research routine that fits you. Choose what to
              follow, what matters and where your updates belong.
            </p>
            <div className="hero-actions">
              <a className="button primary" href={workspace.setup}>
                Build your brief <ArrowRight size={17} aria-hidden="true" />
              </a>
              <a className="text-link" href="#how-it-works">
                <Play size={16} aria-hidden="true" /> See how it works
              </a>
            </div>
          </div>
          <MarketPreview configureUrl={workspace.createWatch} />
        </section>
        <section className="watch-method" aria-labelledby="price-watch-title">
          <div className="method-intro">
            <h2 id="price-watch-title">
              A move is a signal. <br />
              Not the whole story.
            </h2>
            <p>
              A price tells you what changed. Your sources help you understand the context. Bring
              both into a brief built around what matters to you.
            </p>
          </div>
          <WorkflowWalkthrough />
        </section>
        <section className="market-invitation">
          <div>
            <h2>Start with a source you trust.</h2>
            <p>Choose your research. Make the brief yours.</p>
          </div>
          <a className="button primary" href={workspace.setup}>
            Get started <ArrowRight size={17} aria-hidden="true" />
          </a>
        </section>
      </main>
      <footer className="market-footer">
        <Brand />
        <p>
          <Check size={15} aria-hidden="true" /> Information, not investment advice.
        </p>
        <a href="https://sectors.app" target="_blank" rel="noreferrer">
          Explore Sectors
        </a>
      </footer>
    </div>
  );
}
