import { EventEmitter } from "events"
import { Identifier } from "@/id/id"

export type GlobalEvent = {
  directory?: string
  project?: string
  workspace?: string
  payload: any
}

class GlobalBusEmitter extends EventEmitter<{
  event: [GlobalEvent]
}> {
  override emit(eventName: "event", event: GlobalEvent): boolean {
    if (event.payload && typeof event.payload === "object" && !("id" in event.payload)) {
      event.payload.id = event.payload.syncEvent?.id ?? Identifier.create("evt", "ascending")
    }
    return super.emit(eventName, event)
  }
}

export const GlobalBus = new GlobalBusEmitter()
// GlobalBus is a process-wide broadcast bus: every concurrent SSE subscriber (the
// /event and /global handlers each do GlobalBus.on("event", ...)) is one listener,
// and a normal multi-client/multi-tab session legitimately exceeds Node's default
// cap of 10. Without lifting it the runtime prints a spurious
// "MaxListenersExceededWarning ... possible memory leak" on the 11th subscriber.
// 0 = unlimited; subscribers are still released on disconnect via acquireRelease.
GlobalBus.setMaxListeners(0)
