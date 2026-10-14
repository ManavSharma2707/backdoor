import { describe, expect, it } from "vitest";
import {
  addDays,
  compactMoney,
  dateRange,
  daysBetween,
  formatDate,
  formatDateTime,
  formatDayMonth,
  formatTime,
  money,
  parseTypedDate,
  percentOfOne,
  percentValue,
  plural,
  quantity,
  relativeDays,
  signedQuantity,
  todayIso,
  weekLabel,
  weekStartOf,
} from "./format";

describe("money", () => {
  it("groups the Indian way", () => {
    expect(money("182340")).toBe("₹1,82,340");
    expect(money("1234567.8")).toBe("₹12,34,568");
    expect(money("999")).toBe("₹999");
  });
  it("shows two decimals when asked", () => {
    expect(money("182340.5", 2)).toBe("₹1,82,340.50");
    expect(money("0", 2)).toBe("₹0.00");
  });
  it("shows zero without a sign and negatives with a leading minus", () => {
    expect(money("0")).toBe("₹0");
    expect(money("-0.2")).toBe("₹0");
    expect(money("-1500")).toBe("-₹1,500");
    expect(money("-1500.5", 2)).toBe("-₹1,500.50");
  });
  it("returns empty text for missing or broken values", () => {
    expect(money(null)).toBe("");
    expect(money(undefined)).toBe("");
    expect(money("")).toBe("");
    expect(money("abc")).toBe("");
  });
});

describe("compactMoney", () => {
  it("keeps amounts under one lakh in full", () => {
    expect(compactMoney("99999")).toBe("₹99,999");
    expect(compactMoney("0")).toBe("₹0");
  });
  it("uses lakh and crore", () => {
    expect(compactMoney("100000")).toBe("₹1 lakh");
    expect(compactMoney("193299.88")).toBe("₹1.9 lakh");
    expect(compactMoney("9950000")).toBe("₹99.5 lakh");
    expect(compactMoney("10000000")).toBe("₹1 crore");
    expect(compactMoney("12000000")).toBe("₹1.2 crore");
  });
  it("rolls 99.95 lakh over to a crore", () => {
    expect(compactMoney("9999999")).toBe("₹1 crore");
  });
  it("keeps the sign on negatives", () => {
    expect(compactMoney("-250000")).toBe("-₹2.5 lakh");
    expect(compactMoney("-500")).toBe("-₹500");
  });
});

describe("quantity", () => {
  it("groups and trims", () => {
    expect(quantity("1250")).toBe("1,250");
    expect(quantity("12.500")).toBe("12.5");
    expect(quantity("0.125")).toBe("0.125");
    expect(quantity("123456")).toBe("1,23,456");
  });
  it("handles zero, negatives and missing values", () => {
    expect(quantity("0.000")).toBe("0");
    expect(quantity("-4")).toBe("-4");
    expect(quantity("-0.0001")).toBe("0");
    expect(quantity(null)).toBe("");
  });
  it("adds a plus sign for stock changes", () => {
    expect(signedQuantity("12")).toBe("+12");
    expect(signedQuantity("-4")).toBe("-4");
    expect(signedQuantity("0")).toBe("0");
  });
});

describe("percent and plural", () => {
  it("formats shares", () => {
    expect(percentOfOne(0.31)).toBe("31%");
    expect(percentOfOne("0.3125", 1)).toBe("31.3%");
    expect(percentOfOne(0)).toBe("0%");
    expect(percentValue("5.00")).toBe("5%");
    expect(percentValue("12.50", 1)).toBe("12.5%");
    expect(percentValue(null)).toBe("");
  });
  it("picks one or many", () => {
    expect(plural(1, "bill")).toBe("1 bill");
    expect(plural(0, "bill")).toBe("0 bills");
    expect(plural(1200, "bill")).toBe("1,200 bills");
    expect(plural(2, "batch", "batches")).toBe("2 batches");
  });
});

describe("dates", () => {
  it("formats business dates without moving them", () => {
    expect(formatDate("2026-10-12")).toBe("12 Oct 2026");
    expect(formatDate("2026-01-01")).toBe("1 Jan 2026");
    expect(formatDayMonth("2026-12-31")).toBe("31 Dec");
    expect(formatDate("")).toBe("");
    expect(formatDate(null)).toBe("");
    expect(formatDate("nonsense")).toBe("");
  });
  it("shows instants in IST", () => {
    // 20:00 UTC on 11 Oct is 1:30 am on 12 Oct in India.
    expect(formatDate("2026-10-11T20:00:00Z")).toBe("12 Oct 2026");
    expect(formatTime("2026-10-11T20:00:00Z")).toBe("1:30 am");
    expect(formatTime("2026-10-12T00:32:00Z")).toBe("6:02 am");
    expect(formatTime("2026-10-12T06:30:00Z")).toBe("12:00 pm");
    expect(formatTime("2026-10-11T18:30:00Z")).toBe("12:00 am");
    expect(formatDateTime("2026-10-11T16:26:18Z")).toBe("11 Oct 2026, 9:56 pm");
  });
  it("finds today in India, not in UTC", () => {
    expect(todayIso(new Date("2026-10-11T19:00:00Z"))).toBe("2026-10-12");
    expect(todayIso(new Date("2026-10-11T17:00:00Z"))).toBe("2026-10-11");
  });
  it("does date arithmetic across months and years", () => {
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDays("2026-01-01", -1)).toBe("2025-12-31");
    expect(addDays("2028-02-28", 1)).toBe("2028-02-29");
    expect(daysBetween("2026-10-12", "2026-10-16")).toBe(4);
    expect(daysBetween("2026-10-16", "2026-10-12")).toBe(-4);
  });
  it("finds the Monday of a week", () => {
    expect(weekStartOf("2026-10-12")).toBe("2026-10-12");
    expect(weekStartOf("2026-10-18")).toBe("2026-10-12");
    expect(weekStartOf("2026-10-19")).toBe("2026-10-19");
    expect(weekLabel("2026-10-12")).toBe("Week of 12 Oct");
  });
  it("writes ranges", () => {
    expect(dateRange("2026-10-12", "2026-10-18")).toBe("12 to 18 Oct 2026");
    expect(dateRange("2026-09-28", "2026-10-04")).toBe("28 Sep to 4 Oct 2026");
    expect(dateRange("2026-12-28", "2027-01-03")).toBe("28 Dec 2026 to 3 Jan 2027");
    expect(dateRange("2026-10-12", "2026-10-12")).toBe("12 Oct 2026");
  });
  it("describes days relative to today", () => {
    const today = "2026-10-13";
    expect(relativeDays("2026-10-13", today)).toBe("today");
    expect(relativeDays("2026-10-14", today)).toBe("tomorrow");
    expect(relativeDays("2026-10-12", today)).toBe("yesterday");
    expect(relativeDays("2026-10-16", today)).toBe("in 3 days (16 Oct)");
    expect(relativeDays("2026-10-09", today)).toBe("4 days ago (9 Oct)");
  });
  it("reads typed dates", () => {
    expect(parseTypedDate("12 Oct 2026")).toBe("2026-10-12");
    expect(parseTypedDate("12/10/2026")).toBe("2026-10-12");
    expect(parseTypedDate("2026-10-12")).toBe("2026-10-12");
    expect(parseTypedDate("1 october 2026")).toBe("2026-10-01");
    expect(parseTypedDate("31/02/2026")).toBeNull();
    expect(parseTypedDate("12 Foo 2026")).toBeNull();
    expect(parseTypedDate("")).toBeNull();
  });
});
