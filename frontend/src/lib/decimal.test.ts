import { describe, expect, it } from "vitest";
import { lineTotalPaise, paiseToString, toScaled } from "./decimal";

describe("decimal helpers", () => {
  it("scales plain decimals", () => {
    expect(toScaled("12.5", 3)).toBe(12500n);
    expect(toScaled("-0.25", 2)).toBe(-25n);
    expect(toScaled("1.2345", 2)).toBe(123n);
    expect(toScaled("abc", 2)).toBeNull();
    expect(toScaled("", 2)).toBeNull();
  });
  it("prices a line exactly", () => {
    expect(lineTotalPaise("3", "68", "")).toBe(20400n);
    expect(lineTotalPaise("0.5", "99.99", "")).toBe(5000n);
    expect(lineTotalPaise("2", "21.2128", "")).toBe(4243n);
    expect(lineTotalPaise("3", "10", "5.50")).toBe(2450n);
    expect(lineTotalPaise("x", "10", "")).toBeNull();
  });
  it("does not drift the way floats do", () => {
    expect(lineTotalPaise("3", "0.1", "")).toBe(30n);
    expect(paiseToString(lineTotalPaise("3", "1.1", "") ?? 0n)).toBe("3.30");
  });
  it("writes paise as text", () => {
    expect(paiseToString(0n)).toBe("0.00");
    expect(paiseToString(5n)).toBe("0.05");
    expect(paiseToString(18234050n)).toBe("182340.50");
    expect(paiseToString(-250n)).toBe("-2.50");
  });
});
