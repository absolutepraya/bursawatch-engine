"use client";

import { useEffect } from "react";

/**
 * Scroll-triggered story beats. Elements marked data-reveal, data-stagger or
 * data-seq stay fully visible until this runs, so the page works without
 * JavaScript. Groups already on screen are marked first so nothing flashes
 * hidden; the rest play once as they enter the viewport. Reduced motion shows
 * the finished state at once.
 */
const SELECTOR = "[data-reveal],[data-stagger],[data-seq]";

export function MotionInit() {
  useEffect(() => {
    const root = document.documentElement;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    const targets = Array.from(document.querySelectorAll<HTMLElement>(SELECTOR));
    const show = (el: Element) => el.setAttribute("data-inview", "");
    let observer: IntersectionObserver | undefined;

    const stop = () => {
      observer?.disconnect();
      root.removeAttribute("data-motion");
      targets.forEach(show);
    };

    if (reduce.matches) {
      stop();
    } else {
      const pending = targets.filter((el) => {
        if (el.getBoundingClientRect().top < window.innerHeight * 0.9) {
          show(el);
          return false;
        }
        return true;
      });
      observer = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            show(entry.target);
            observer?.unobserve(entry.target);
          }
        },
        { threshold: 0.15, rootMargin: "0px 0px -12% 0px" },
      );
      pending.forEach((el) => observer?.observe(el));
      root.setAttribute("data-motion", "on");
    }

    const onChange = () => {
      if (reduce.matches) stop();
    };
    reduce.addEventListener("change", onChange);
    return () => {
      reduce.removeEventListener("change", onChange);
      observer?.disconnect();
      root.removeAttribute("data-motion");
    };
  }, []);

  return null;
}
