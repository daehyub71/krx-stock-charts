"use client";

/**
 * 캔들 차트 (DESIGN §3 차트 규격 · SPEC F6).
 *
 * lightweight-charts는 캔버스에 그리므로 CSS 변수를 그대로 줄 수 없다.
 * 테마 토큰을 실제 색으로 읽어 시리즈 옵션에 주입하고, 테마가 바뀌면 다시 읽는다.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import {
  formatTickMark,
  maSeries,
  readChartPalette,
  toCandles,
  toVolumeBars,
  type ChartPalette,
  type MaLine,
  type VolumeMode,
} from "@/lib/chart";
import { amount as fmtAmount, pct, volume as fmtVolume, won } from "@/lib/format";
import type { Bar, Timeframe } from "@/lib/types";

export interface CandleChartProps {
  /** 워밍업을 포함한 전체 봉 (지표 계산용). */
  bars: readonly Bar[];
  /** 화면에 그리지 않을 앞부분 봉 수. */
  warmup: number;
  timeframe: Timeframe;
  height?: number;
  /** 하단 pane에 거래량과 거래대금 중 무엇을 그릴지. */
  volumeMode?: VolumeMode;
}

interface HoverInfo {
  bar: Bar;
  previous: Bar | null;
  x: number;
}

/** 문서에 현재 적용된 테마를 읽는다 (명시 선택 → 시스템 설정 순). */
function currentTheme(): "light" | "dark" {
  if (typeof window === "undefined") return "light";
  const stamped = document.documentElement.getAttribute("data-theme");
  if (stamped === "dark" || stamped === "light") return stamped;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function CandleChart({
  bars,
  warmup,
  timeframe,
  height = 380,
  volumeMode = "volume",
}: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const maRefs = useRef<ISeriesApi<"Line">[]>([]);

  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const [legend, setLegend] = useState<MaLine[]>([]);

  // 매 렌더마다 새 배열이 되면 아래 effect가 무한히 다시 돈다.
  const visible = useMemo(() => bars.slice(warmup), [bars, warmup]);

  // 테마 변화를 감지한다 — 토글(data-theme)과 시스템 설정 양쪽.
  useEffect(() => {
    const sync = () => setTheme(currentTheme());
    sync();

    const observer = new MutationObserver(sync);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", sync);

    return () => {
      observer.disconnect();
      media.removeEventListener("change", sync);
    };
  }, []);

  // 차트 생성 — 컨테이너 하나당 한 번만.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart = createChart(el, {
      height,
      layout: {
        background: { color: "transparent" },
        attributionLogo: false,
        panes: { separatorColor: "transparent" },
      },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: {
        borderVisible: false,
        rightOffset: 4,
        fixLeftEdge: true,
        fixRightEdge: true,
        tickMarkFormatter: (time: unknown, tickType: number) => formatTickMark(time, tickType),
      },
      crosshair: { mode: 0 },
      handleScale: { axisPressedMouseMove: false },
      localization: {
        locale: "ko-KR",
        // priceFormatter를 여기 두면 **모든 pane의 축을 덮어써서** 거래대금 축까지
        // 원 단위로 찍힌다. 축 포맷은 시리즈별 priceFormat으로 준다.
        // 크로스헤어 하단 라벨. 기본값은 "12 8월 '26"처럼 순서가 뒤섞여 나온다.
        timeFormatter: (time: unknown) =>
          typeof time === "string"
            ? time
            : new Date((time as number) * 1000).toISOString().slice(0, 10),
      },
    });

    chartRef.current = chart;
    candleRef.current = chart.addSeries(CandlestickSeries, {
      priceLineVisible: false,
      lastValueVisible: true,
      priceFormat: { type: "custom", minMove: 1, formatter: (v: number) => won(v) },
    });
    // 거래량은 별도 pane에 둔다 — 가격 축과 눈금을 섞지 않는다.
    volumeRef.current = chart.addSeries(
      HistogramSeries,
      {
        priceLineVisible: false,
        lastValueVisible: false,
        priceFormat: { type: "custom", minMove: 1, formatter: (v: number) => fmtVolume(v) },
      },
      1,
    );
    chart.panes()[1]?.setHeight(Math.round(height * 0.26));

    const resize = () => chart.applyOptions({ width: el.clientWidth });
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(el);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      maRefs.current = [];
    };
  }, [height]);

  // 데이터·테마가 바뀌면 시리즈를 다시 채운다.
  useEffect(() => {
    const chart = chartRef.current;
    const candle = candleRef.current;
    const vol = volumeRef.current;
    if (!chart || !candle || !vol || visible.length === 0) return;

    const palette: ChartPalette = readChartPalette();

    candle.applyOptions({
      upColor: palette.up,
      downColor: palette.down,
      borderUpColor: palette.up,
      borderDownColor: palette.down,
      wickUpColor: palette.up,
      wickDownColor: palette.down,
    });
    candle.setData(toCandles(visible) as never);

    // custom 포맷은 minMove가 있어야 축에 실제로 적용된다 — 없으면 원시 숫자가 그대로 찍힌다.
    vol.applyOptions({
      priceFormat: {
        type: "custom",
        minMove: 1,
        formatter: (v: number) => (volumeMode === "amount" ? fmtAmount(v) : fmtVolume(v)),
      },
    });
    vol.setData(
      toVolumeBars(
        visible,
        { up: `${palette.up}55`, down: `${palette.down}55` },
        volumeMode,
      ) as never,
    );

    chart.applyOptions({
      layout: { textColor: palette.ink3 },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: palette.rule2 },
      },
      crosshair: {
        vertLine: { color: palette.ink3, width: 1, style: 2, labelBackgroundColor: palette.ink },
        horzLine: { color: palette.ink3, width: 1, style: 2, labelBackgroundColor: palette.ink },
      },
    });

    // MA선 — 주기가 바뀌면 개수도 바뀌므로 매번 지우고 다시 만든다.
    for (const s of maRefs.current) chart.removeSeries(s);
    maRefs.current = [];

    const lines = maSeries(bars, timeframe, warmup, palette.ma);
    for (const line of lines) {
      if (line.points.length === 0) continue;
      const series = chart.addSeries(LineSeries, {
        color: line.color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      series.setData(line.points as never);
      maRefs.current.push(series);
    }
    setLegend(lines);

    chart.timeScale().fitContent();
  }, [bars, warmup, timeframe, theme, visible, volumeMode]);

  // 크로스헤어 → 툴팁
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const byDate = new Map(visible.map((b, i) => [b.d, i]));

    const handler = (param: { time?: Time; point?: { x: number } }) => {
      if (param.time === undefined || param.point === undefined) {
        setHover(null);
        return;
      }
      const index = byDate.get(String(param.time));
      if (index === undefined) {
        setHover(null);
        return;
      }
      setHover({
        bar: visible[index],
        previous: index > 0 ? visible[index - 1] : null,
        x: param.point.x,
      });
    };

    chart.subscribeCrosshairMove(handler);
    return () => chart.unsubscribeCrosshairMove(handler);
  }, [visible]);

  // 키보드 접근성 — ←/→로 봉을 훑는다 (DESIGN §3).
  const [focusIndex, setFocusIndex] = useState<number | null>(null);
  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const step = e.key === "ArrowRight" ? 1 : -1;
    const next = Math.max(
      0,
      Math.min(visible.length - 1, (focusIndex ?? visible.length - 1) + step),
    );
    setFocusIndex(next);
    const bar = visible[next];
    setHover({ bar, previous: next > 0 ? visible[next - 1] : null, x: 0 });
    if (candleRef.current) {
      chartRef.current?.setCrosshairPosition(bar.c, bar.d as unknown as Time, candleRef.current);
    }
  }

  const hoverChange =
    hover && hover.previous ? (hover.bar.c / hover.previous.c - 1) * 100 : null;

  return (
    <div className="relative">
      {legend.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 px-5 pt-3 text-[11.5px] text-[var(--ink-2)]">
          {legend.map((l) => (
            <span key={l.period} className="inline-flex items-center gap-1.5">
              <i
                aria-hidden="true"
                className="inline-block h-[2.5px] w-3.5 rounded-full"
                style={{ background: l.color }}
              />
              {l.label}{" "}
              <b className="num font-semibold text-[var(--ink)]">
                {l.latest === null ? "—" : won(l.latest)}
              </b>
            </span>
          ))}
        </div>
      )}

      <div
        ref={containerRef}
        tabIndex={0}
        role="img"
        aria-label={`캔들 차트. 좌우 방향키로 각 봉의 시세를 읽을 수 있습니다. 현재 ${visible.length}봉 표시 중.`}
        onKeyDown={onKeyDown}
        className="w-full px-2 pb-2 outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
      />

      {hover && (
        <div
          role="status"
          aria-live="polite"
          className="pointer-events-none absolute left-5 top-10 z-10 min-w-[152px] rounded-lg border border-[var(--rule)] bg-[var(--surface)] p-2.5 shadow-lg"
        >
          <div className="num mb-1.5 text-[11px] text-[var(--ink-3)]">{hover.bar.d}</div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3.5 gap-y-0.5 text-[12px]">
            <dt className="text-[var(--ink-3)]">시가</dt>
            <dd className="num text-right font-medium">{won(hover.bar.o)}</dd>
            <dt className="text-[var(--ink-3)]">고가</dt>
            <dd className="num text-right font-medium">{won(hover.bar.h)}</dd>
            <dt className="text-[var(--ink-3)]">저가</dt>
            <dd className="num text-right font-medium">{won(hover.bar.l)}</dd>
            <dt className="text-[var(--ink-3)]">종가</dt>
            <dd
              className="num text-right font-semibold"
              style={{ color: hover.bar.c >= hover.bar.o ? "var(--up)" : "var(--down)" }}
            >
              {won(hover.bar.c)}
            </dd>
            <dt className="text-[var(--ink-3)]">등락률</dt>
            <dd
              className="num text-right font-medium"
              style={{
                color:
                  hoverChange === null
                    ? undefined
                    : hoverChange >= 0
                      ? "var(--up)"
                      : "var(--down)",
              }}
            >
              {hoverChange === null ? "—" : pct(hoverChange)}
            </dd>
            <dt className="text-[var(--ink-3)]">거래량</dt>
            <dd className="num text-right font-medium">{fmtVolume(hover.bar.v)}</dd>
            <dt className="text-[var(--ink-3)]">거래대금</dt>
            <dd className="num text-right font-medium">{fmtAmount(hover.bar.a)}</dd>
          </dl>
        </div>
      )}
    </div>
  );
}
