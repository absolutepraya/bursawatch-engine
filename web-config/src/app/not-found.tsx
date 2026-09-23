import { ArrowLeft } from "lucide-react";
import Link from "next/link";

export default function NotFound() {
  return (
    <main className="not-found">
      <h1>Page not found</h1>
      <p>Open your workspace to find your watches.</p>
      <Link className="button primary" href="/app/overview">
        <ArrowLeft aria-hidden="true" size={17} /> Back to overview
      </Link>
    </main>
  );
}
