import { downloadChartImage } from "../chart-export";

it("bubbles an attached download anchor to the native bridge and removes it afterward", () => {
  const create = vi.fn((_blob: Blob) => "blob:chart");
  const revoke = vi.fn();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
  let download: string | undefined;
  const listener = (event: MouseEvent) => {
    event.preventDefault();
    const anchor = event.target as HTMLAnchorElement;
    expect(anchor.isConnected).toBe(true);
    expect(anchor.href).toBe("blob:chart");
    download = anchor.download;
  };
  document.addEventListener("click", listener, { once: true });
  downloadChartImage("data:image/png;base64,AAAA", "capital.png");
  expect(download).toBe("capital.png");
  expect(document.querySelector("a[download]")).toBeNull();
  expect(create.mock.calls[0][0]).toMatchObject({ type: "image/png", size: 3 });
  expect(revoke).toHaveBeenCalledWith("blob:chart");
});
