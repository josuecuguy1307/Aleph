import { userFacingError } from "../user-facing-error";

describe("user-facing errors", () => {
  it("extracts the deadline explanation without displaying JSON or provider metadata", () => {
    const error = 'provider_stream_error provider=openai: APIError: HTTP 504: {"error":{"message":"[Codex] el deadline llegó agotado","type":"cli_timeout","turno_id":"private-id"}}';
    expect(userFacingError(error, "Se ha agotado el tiempo.")).toBe("[Codex] el deadline llegó agotado");
  });
  it("handles nested and truncated envelopes", () => {
    expect(userFacingError(JSON.stringify({error:{message:JSON.stringify({detail:"Intente otra vez"})}}), "Error")).toBe("Intente otra vez");
    expect(userFacingError('HTTP 504: {"error":', "Error")).toBe("Error (HTTP 504)");
  });
});
