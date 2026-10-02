import { For, Show, createMemo, createResource, type JSX } from "solid-js"
import type { SessionTraceResponse } from "@synsci/sdk/v2/client"
import { useSDK } from "@/context/sdk"
import { IconRefresh } from "@/atlas/shared/Icon"
import { formatClock, sourceLabel, traceActivity, traceCounts, traceMetrics } from "./session-trace-model"
import "./SessionTraceSurface.css"

export function SessionTraceSurface(props: { session: string }): JSX.Element {
  const sdk = useSDK()
  const [trace, api] = createResource(
    () => (props.session && props.session !== "new" ? props.session : false),
    async (sessionID) => {
      const response = await sdk.client.session.trace({ sessionID })
      if (!response.data) throw new Error("The local trace did not return any data.")
      return response.data as SessionTraceResponse
    },
  )
  const activity = createMemo(() => (trace() ? traceActivity(trace()!) : []))

  return (
    <section class="session-trace" aria-label="Session trace">
      <Show
        when={props.session && props.session !== "new"}
        fallback={
          <TraceState
            title="No session trace yet"
            detail="Send a prompt to start a session. Observable work will appear here as it runs."
          />
        }
      >
        <Show
          when={!trace.loading}
          fallback={
            <div class="session-trace__skeleton" role="status" aria-label="Loading session trace">
              <span />
              <span />
              <span />
            </div>
          }
        >
          <Show
            when={!trace.error && trace()}
            fallback={
              <TraceState
                title="Trace unavailable"
                detail={trace.error instanceof Error ? trace.error.message : String(trace.error)}
                action={() => void api.refetch()}
              />
            }
          >
            {(data) => (
              <>
                <header class="session-trace__intro">
                  <div>
                    <span class="session-trace__eyebrow">Local observable record</span>
                    <h2>{data().session.title}</h2>
                    <p>
                      Timing, cost, approvals, and results from this session. Hidden reasoning and raw tool output are
                      never stored here.
                    </p>
                  </div>
                  <button
                    type="button"
                    class="session-trace__refresh"
                    title="Refresh trace"
                    aria-label="Refresh trace"
                    onClick={() => void api.refetch()}
                  >
                    <IconRefresh size={13} />
                  </button>
                </header>

                <dl class="session-trace__metrics">
                  <For each={traceMetrics(data())}>
                    {(metric) => (
                      <div>
                        <dt>{metric.label}</dt>
                        <dd>{metric.value}</dd>
                        <span>{metric.detail}</span>
                      </div>
                    )}
                  </For>
                </dl>

                <dl class="session-trace__counts" aria-label="Session work counts">
                  <For each={traceCounts(data())}>
                    {(count) => (
                      <div data-alert={count.label === "failures" && count.value > 0 ? "true" : undefined}>
                        <dt>{count.label}</dt>
                        <dd>{count.value}</dd>
                        <Show when={count.note}>
                          <span>{count.note}</span>
                        </Show>
                      </div>
                    )}
                  </For>
                </dl>

                <Show when={data().inference.length > 0}>
                  <section class="session-trace__route" aria-label="Inference route">
                    <span>Inference</span>
                    <strong>
                      {data().inference[0].provider} / {data().inference[0].model}
                    </strong>
                    <small>
                      {sourceLabel(data().inference[0].source)} · {data().inference[0].effort} effort
                    </small>
                  </section>
                </Show>

                <section class="session-trace__activity" aria-label="Observable activity">
                  <div class="session-trace__section-title">
                    <h3>Observable activity</h3>
                    <span>{activity().length}</span>
                  </div>
                  <Show
                    when={activity().length > 0}
                    fallback={
                      <p class="session-trace__empty">
                        No model, tool, approval, or result events have been recorded yet.
                      </p>
                    }
                  >
                    <ol>
                      <For each={activity()}>
                        {(item) => (
                          <li data-kind={item.kind} data-status={item.status}>
                            <time datetime={new Date(item.at).toISOString()}>{formatClock(item.at)}</time>
                            <span class="session-trace__mark" aria-hidden="true" />
                            <div>
                              <strong>{item.label}</strong>
                              <span>{item.detail}</span>
                            </div>
                          </li>
                        )}
                      </For>
                    </ol>
                  </Show>
                </section>

                <footer class="session-trace__privacy">
                  <span>Local to this machine</span>
                  <span>Atlas not required</span>
                  <span>No chain-of-thought</span>
                </footer>
              </>
            )}
          </Show>
        </Show>
      </Show>
    </section>
  )
}

function TraceState(props: { title: string; detail: string; action?: () => void }): JSX.Element {
  return (
    <div class="session-trace__state">
      <span aria-hidden="true">···</span>
      <strong>{props.title}</strong>
      <p>{props.detail}</p>
      <Show when={props.action}>
        {(action) => (
          <button type="button" onClick={action()}>
            Try again
          </button>
        )}
      </Show>
    </div>
  )
}
