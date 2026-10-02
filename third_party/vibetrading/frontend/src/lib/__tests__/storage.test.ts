import type {} from "vitest/jsdom";
import { safeGet, safeSet, safeRemove } from "../storage";

describe("browser Storage test environment", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("uses jsdom's real window Storage instead of Node's native global", () => {
    expect(globalThis.localStorage).toBe(jsdom.window.localStorage);
    expect(globalThis.sessionStorage).toBe(jsdom.window.sessionStorage);
    expect(localStorage).toBeInstanceOf(Storage);
    expect(sessionStorage).toBeInstanceOf(Storage);
  });

  it("keeps persistent and session values separate", () => {
    localStorage.setItem("qa-storage", "persistent");
    sessionStorage.setItem("qa-storage", "session");
    expect(localStorage.getItem("qa-storage")).toBe("persistent");
    expect(sessionStorage.getItem("qa-storage")).toBe("session");
  });

  it("round-trips and removes values through the application wrappers", () => {
    expect(safeGet("qa-storage")).toBeNull();
    safeSet("qa-storage", "dark");
    expect(safeGet("qa-storage")).toBe("dark");
    expect(localStorage.length).toBe(1);
    safeRemove("qa-storage");
    expect(safeGet("qa-storage")).toBeNull();
    expect(localStorage.length).toBe(0);
  });

  it("returns a default when DOM storage reads are blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("Blocked", "SecurityError");
    });
    expect(safeGet("qa-storage")).toBeNull();
  });

  it("tolerates DOM storage quota errors on writes", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("Full", "QuotaExceededError");
    });
    expect(() => safeSet("qa-storage", "dark")).not.toThrow();
    expect(localStorage.getItem("qa-storage")).toBeNull();
  });

  it("tolerates blocked DOM storage removals", () => {
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new DOMException("Blocked", "SecurityError");
    });
    expect(() => safeRemove("qa-storage")).not.toThrow();
  });
});
