import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import TickerRail, { filterTickers, sparkPath } from "@/components/TickerRail";
import type { Ticker } from "@/lib/types";

const TICKERS: Ticker[] = [
  { ticker: "005930", name: "삼성전자", market: "KOSPI", sector: "전기·전자" },
  { ticker: "000660", name: "SK하이닉스", market: "KOSPI", sector: "전기·전자" },
  { ticker: "0126Z0", name: "삼성에피스홀딩스", market: "KOSPI", sector: "기타금융" },
];

describe("filterTickers", () => {
  it("returns everything for an empty query", () => {
    expect(filterTickers(TICKERS, "")).toHaveLength(3);
    expect(filterTickers(TICKERS, "   ")).toHaveLength(3);
  });

  it("matches on the Korean name", () => {
    expect(filterTickers(TICKERS, "하이닉스").map((t) => t.ticker)).toEqual(["000660"]);
  });

  it("matches on a partial ticker code", () => {
    expect(filterTickers(TICKERS, "0059").map((t) => t.ticker)).toEqual(["005930"]);
  });

  it("finds alphanumeric tickers case-insensitively", () => {
    // 0126Z0은 대문자 Z를 포함한다 — 소문자로 쳐도 찾혀야 한다
    expect(filterTickers(TICKERS, "0126z0").map((t) => t.ticker)).toEqual(["0126Z0"]);
  });

  it("matches a name prefix shared by two entries", () => {
    expect(filterTickers(TICKERS, "삼성")).toHaveLength(2);
  });

  it("returns nothing when there is no match", () => {
    expect(filterTickers(TICKERS, "존재하지않는종목")).toEqual([]);
  });
});

describe("sparkPath", () => {
  it("returns an empty path when there are too few points", () => {
    expect(sparkPath([], 58, 20)).toBe("");
    expect(sparkPath([100], 58, 20)).toBe("");
  });

  it("starts with a move command and spans the full width", () => {
    const d = sparkPath([1, 2, 3], 60, 20);
    expect(d.startsWith("M0.0")).toBe(true);
    expect(d).toContain("L60.0");
  });

  it("puts the maximum at the top and the minimum at the bottom", () => {
    // y축은 뒤집혀 있다 — 값이 클수록 y가 작다
    const d = sparkPath([10, 20], 100, 20);
    expect(d).toBe("M0.0 20.0 L100.0 0.0");
  });

  it("does not divide by zero for a flat series", () => {
    expect(sparkPath([5, 5, 5], 60, 20)).not.toContain("NaN");
  });
});

describe("TickerRail", () => {
  const noop = () => {};

  it("renders every ticker with its code", () => {
    render(<TickerRail tickers={TICKERS} selected="005930" onSelect={noop} />);
    expect(screen.getByText("삼성전자")).toBeInTheDocument();
    expect(screen.getByText("0126Z0")).toBeInTheDocument();
    expect(screen.getAllByRole("option")).toHaveLength(3);
  });

  it("filters the list as the user types", () => {
    render(<TickerRail tickers={TICKERS} selected="005930" onSelect={noop} />);
    fireEvent.change(screen.getByLabelText("종목 검색"), { target: { value: "하이닉스" } });
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.getByText("SK하이닉스")).toBeInTheDocument();
  });

  it("marks the selected ticker for assistive tech", () => {
    render(<TickerRail tickers={TICKERS} selected="000660" onSelect={noop} />);
    const selected = screen.getAllByRole("option").filter((el) => el.getAttribute("aria-selected") === "true");
    expect(selected).toHaveLength(1);
    expect(selected[0]).toHaveTextContent("SK하이닉스");
  });

  it("reports the filtered list so the parent can load only what is shown", () => {
    const onVisibleChange = vi.fn();
    render(
      <TickerRail tickers={TICKERS} selected="005930" onSelect={noop} onVisibleChange={onVisibleChange} />,
    );
    expect(onVisibleChange).toHaveBeenCalledWith(["005930", "000660", "0126Z0"]);

    fireEvent.change(screen.getByLabelText("종목 검색"), { target: { value: "하이닉스" } });
    expect(onVisibleChange).toHaveBeenLastCalledWith(["000660"]);
  });

  it("calls onSelect with the clicked ticker", () => {
    const onSelect = vi.fn();
    render(<TickerRail tickers={TICKERS} selected="005930" onSelect={onSelect} />);
    fireEvent.click(screen.getByText("SK하이닉스"));
    expect(onSelect).toHaveBeenCalledWith("000660");
  });

  it("shows the match count while searching and the total otherwise", () => {
    render(<TickerRail tickers={TICKERS} selected="005930" onSelect={noop} />);
    expect(screen.getByText("KOSPI·KOSDAQ 3종목")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("종목 검색"), { target: { value: "삼성" } });
    expect(screen.getByText("2종목 검색됨")).toBeInTheDocument();
  });

  it("renders a dash instead of a percentage when sparkline data is missing", () => {
    render(<TickerRail tickers={TICKERS} selected="005930" onSelect={noop} />);
    expect(screen.getAllByText("—")).toHaveLength(3);
  });

  it("computes the change from the last two sparkline closes", () => {
    const sparklines = new Map([["005930", [100, 110]]]);
    render(<TickerRail tickers={TICKERS} sparklines={sparklines} selected="005930" onSelect={noop} />);
    expect(screen.getByText("+10.00%")).toBeInTheDocument();
  });
});
