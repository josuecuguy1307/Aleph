import { candleValues } from "../chart-tooltip";

describe("candlestick tooltip", () => {
  it("does not mistake ECharts' category index for the opening price", () => {
    expect(candleValues({ data: [496.73, 498.13, 494.64, 500.02], value: [222, 496.73, 498.13, 494.64, 500.02] }))
      .toEqual([496.73, 498.13, 494.64, 500.02]);
    expect(candleValues({ value: [222, 496.73, 498.13, 494.64, 500.02] }))
      .toEqual([496.73, 498.13, 494.64, 500.02]);
  });
  it("does not render incomplete or nonfinite prices", () => {
    expect(candleValues({ data: [1, 2] })).toBeNull();
    expect(candleValues({ data: [1, NaN, 2, 3] })).toBeNull();
  });
});
