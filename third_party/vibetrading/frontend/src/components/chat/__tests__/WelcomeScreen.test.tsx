import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import i18n from "../../../i18n";
import es from "../../../i18n/locales/es.json";
import { WelcomeScreen } from "../WelcomeScreen";

const frame = vi.hoisted(() => ({ activo: false }));
vi.mock("@/components/layout/aleph-frame", () => ({
  useAlephFrame: () => frame,
}));

const morning = ["Buenos días", "Good morning", "Bonjour", "Buongiorno", "Bom dia", "Guten Morgen", "おはよう"];
const afternoon = ["Buenas tardes", "Good afternoon", "Bon après-midi", "Buon pomeriggio", "Boa tarde", "Guten Tag", "こんにちは"];
const evening = ["Buenas noches", "Good evening", "Bonsoir", "Buonasera", "Boa noite", "Guten Abend", "こんばんは"];

describe("WelcomeScreen", () => {
  const onExample = vi.fn();

  beforeAll(async () => {
    await i18n.changeLanguage("en");
  });

  beforeEach(() => {
    onExample.mockClear();
    frame.activo = false;
    vi.spyOn(Math, "random").mockReturnValue(0);
  });

  afterEach(async () => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    await act(async () => { await i18n.changeLanguage("en"); });
  });

  it.each([
    [0, evening],
    [4, evening],
    [5, morning],
    [11, morning],
    [12, afternoon],
    [17, afternoon],
    [18, afternoon],
    [19, evening],
    [22, evening],
  ] as const)("renders the seven-language Aleph greeting for %i:00", (hour, greetings) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 6, 29, hour));

    render(<WelcomeScreen onExample={onExample} />);

    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveAttribute("aria-live", "polite");
    expect(Array.from(heading.children, (child) => child.textContent)).toEqual(greetings);
    for (const [index, greeting] of greetings.entries()) {
      expect(within(heading).getByText(greeting)).toHaveStyle({ animationDelay: `${index * 5}s` });
    }
    expect(screen.getByLabelText("Aleph")).toBeInTheDocument();
    expect(screen.queryByText("What would you like to research, test, or understand today?")).not.toBeInTheDocument();
  });

  it("rotates one suggestion at a time and hands off all four prompts unchanged", () => {
    const actions = [
      {
        label: "Check if a stock is expensive",
        prompt:
          "Use the financial_rigor tool to verify Kweichow Moutai's valuation: price 1500, EPS 68.6, book value per share 180 — compute PE, PB, ROE exactly, then a three-scenario valuation (growth 12%/8%/0%, PE 22/18/14, 3 years)",
      },
      {
        label: "Options risk check (Greeks)",
        prompt:
          "Calculate option Greeks using Black-Scholes: spot=100, strike=105, risk-free rate=3%, vol=25%, expiry=90 days, analyze Delta/Gamma/Theta/Vega",
      },
      {
        label: "Balance a 3-stock portfolio",
        prompt:
          "Build a risk-parity portfolio with 000001.SZ, 600519.SH, 000858.SZ, backtest for the full year of 2024, and compare with equal-weighted benchmark",
      },
      {
        label: "Buy or sell? Let a committee debate",
        prompt:
          "[Swarm Team Mode] Use the investment_committee preset to evaluate whether to go long or short on 600519.SH given current market conditions",
      },
    ];
    vi.useFakeTimers();
    render(<WelcomeScreen onExample={onExample} />);

    const quickActions = screen.getByRole("group", { name: "Quick actions" });

    for (const [index, action] of actions.entries()) {
      const buttons = within(quickActions).getAllByRole("button");
      expect(buttons).toHaveLength(1);
      expect(buttons[0]).toHaveAccessibleName(action.label);
      fireEvent.click(buttons[0]);
      expect(onExample).toHaveBeenNthCalledWith(index + 1, action.prompt);
      act(() => { vi.advanceTimersByTime(6000); });
    }
    expect(onExample).toHaveBeenCalledTimes(4);
    expect(within(quickActions).getByRole("button", { name: actions[0].label })).toBeInTheDocument();
  });

  it("keeps the selected suggestion still when reduced motion is requested", () => {
    vi.useFakeTimers();
    vi.mocked(Math.random).mockReturnValue(0.5);
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
      media: query,
    }) as MediaQueryList);
    render(<WelcomeScreen onExample={onExample} />);

    const quickActions = screen.getByRole("group", { name: "Quick actions" });
    act(() => { vi.advanceTimersByTime(24000); });
    expect(within(quickActions).getAllByRole("button")).toHaveLength(1);
    expect(within(quickActions).getByRole("button", { name: "Balance a 3-stock portfolio" })).toBeInTheDocument();
  });

  it("clears the suggestion rotation timer when the canvas unmounts", () => {
    vi.useFakeTimers();
    const timerCount = vi.getTimerCount();
    const { unmount } = render(<WelcomeScreen onExample={onExample} />);
    expect(vi.getTimerCount()).toBe(timerCount + 1);
    unmount();
    expect(vi.getTimerCount()).toBe(timerCount);
  });

  it("hands off the Spanish suggestion as a Spanish prompt", async () => {
    await act(async () => { await i18n.changeLanguage("es"); });
    render(<WelcomeScreen onExample={onExample} />);

    const suggestion = await screen.findByRole("button", { name: es.welcome.examples.valuationCheck });
    fireEvent.click(suggestion);
    expect(onExample).toHaveBeenCalledExactlyOnceWith(es.welcome.examples.valuationCheckPrompt);
  });

  it("leaves the Aleph embedded canvas free of standalone suggestions and library", () => {
    frame.activo = true;
    render(<WelcomeScreen onExample={onExample} />);

    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Quick actions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Browse all examples" })).not.toBeInTheDocument();
    expect(document.getElementById("welcome-example-library")).toBeNull();
    expect(onExample).not.toHaveBeenCalled();
  });

  it("reveals eight category tabs and switches example cards from the disclosure", async () => {
    const user = userEvent.setup();
    render(<WelcomeScreen onExample={onExample} />);

    const trigger = screen.getByRole("button", { name: "Browse all examples" });
    const library = document.getElementById("welcome-example-library");
    expect(library).not.toBeNull();
    expect(library).toHaveAttribute("aria-hidden", "true");
    expect(
      screen.queryByRole("button", { name: /A-Share MACD Strategy/ }),
    ).not.toBeInTheDocument();

    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(library).toHaveAttribute("aria-hidden", "false");
    // One category at a time: 8 tab chips, only the active category's cards.
    expect(within(library!).getAllByRole("tab")).toHaveLength(8);
    expect(within(library!).getAllByRole("button")).toHaveLength(3);
    expect(within(library!).getAllByRole("button")[0]).toHaveClass(
      "focus-visible:ring-2",
      "focus-visible:ring-primary/40",
    );
    for (const category of [
      "A-Share Backtest",
      "Research & Analysis",
      "Value Investing",
      "AI Analyst Teams",
      "Document & Web Research",
      "Trade Journal",
      "Trading Connectors",
      "Shadow Account",
    ]) {
      expect(within(library!).getByText(category)).toBeInTheDocument();
    }

    await user.click(within(library!).getByRole("tab", { name: /Value Investing/ }));
    expect(within(library!).getByRole("tab", { name: /Value Investing/ })).toHaveAttribute("aria-selected", "true");
    expect(within(library!).getAllByRole("button")).toHaveLength(4);
    expect(
      within(library!).getByRole("button", { name: /Check if a stock is expensive/ }),
    ).toBeInTheDocument();
  });

  it("closes the example library with Escape and restores focus to its trigger", async () => {
    const user = userEvent.setup();
    render(<WelcomeScreen onExample={onExample} />);

    const trigger = screen.getByRole("button", { name: "Browse all examples" });
    await user.click(trigger);
    const library = document.getElementById("welcome-example-library")!;
    const firstExample = within(library).getAllByRole("button")[0];
    firstExample.focus();

    await user.keyboard("{Escape}");

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(library).toHaveAttribute("aria-hidden", "true");
    expect(trigger).toHaveFocus();
  });

  it("does not render capability chips", () => {
    render(<WelcomeScreen onExample={onExample} />);

    expect(screen.queryByText("Finance Skills Library")).not.toBeInTheDocument();
    expect(screen.queryByText("Swarm Agent Teams")).not.toBeInTheDocument();
    expect(screen.queryByText("Shadow Account Backtest")).not.toBeInTheDocument();
  });
});
