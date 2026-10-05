"use client";

import { useState, type ButtonHTMLAttributes } from "react";

/** Pointer press is the only animated interaction in configuration forms. */
export function SaveButton(props: ButtonHTMLAttributes<HTMLButtonElement>) {
  const [pressed, setPressed] = useState(false);
  return (
    <button
      {...props}
      className="button primary config-save-button"
      data-pointer-pressed={pressed || undefined}
      onPointerDown={() => setPressed(true)}
      onPointerUp={() => setPressed(false)}
      onPointerCancel={() => setPressed(false)}
      onPointerLeave={() => setPressed(false)}
      onBlur={() => setPressed(false)}
    />
  );
}
