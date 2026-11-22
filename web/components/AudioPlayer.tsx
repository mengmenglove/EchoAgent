"use client";

import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import WaveSurfer from "wavesurfer.js";

export type PlayerHandle = { seek: (ms: number) => void; play: () => void };

type Props = {
  url: string;
  onTime?: (ms: number) => void;
  ref?: Ref<PlayerHandle>; // React 19：ref 可以直接作为普通 prop 传入，不再需要 forwardRef
};

export function AudioPlayer({ url, onTime, ref }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const ws = useRef<WaveSurfer | null>(null);
  const onTimeRef = useRef(onTime);
  const [playing, setPlaying] = useState(false);
  const [ready, setReady] = useState(false);

  // 回调存进 ref：父组件每次渲染传入新函数时，不必销毁重建播放器
  useEffect(() => {
    onTimeRef.current = onTime;
  }, [onTime]);

  useEffect(() => {
    if (!container.current) return;
    const w = WaveSurfer.create({
      container: container.current,
      url,
      height: 72,
      waveColor: "#d4d4d8",
      progressColor: "#2563eb",
      cursorColor: "#1d4ed8",
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      fetchParams: { credentials: "include" },
    });
    w.on("ready", () => setReady(true));
    w.on("play", () => setPlaying(true));
    w.on("pause", () => setPlaying(false));
    w.on("finish", () => setPlaying(false));
    w.on("timeupdate", (t) => onTimeRef.current?.(t * 1000));
    ws.current = w;
    // 一定要销毁：否则切换页面或换 url 后会叠出多个播放器、多份音频同时播
    return () => {
      w.destroy();
      ws.current = null;
      setReady(false);
      setPlaying(false);
    };
  }, [url]);

  useImperativeHandle(ref, () => ({
    seek: (ms) => ws.current?.setTime(ms / 1000),
    play: () => void ws.current?.play(),
  }));

  return (
    <div className="flex items-center gap-4">
      <button
        type="button"
        disabled={!ready}
        onClick={() => ws.current?.playPause()}
        className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-blue-600 text-white disabled:bg-zinc-300"
        aria-label={playing ? "暂停" : "播放"}
      >
        {playing ? "❚❚" : "▶"}
      </button>
      <div ref={container} className="min-w-0 flex-1" />
    </div>
  );
}
