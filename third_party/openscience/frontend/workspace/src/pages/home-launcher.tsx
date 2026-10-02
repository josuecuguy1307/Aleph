import { For, Match, Show, Switch, type JSX } from "solid-js"
import { DateTime } from "luxon"
import { IconArrowRight, IconFolder, IconPlus, IconSearch } from "@/atlas/shared/Icon"
import { projectHint, projectName, type LauncherState, type PreparedProject } from "./home-projects"

export function HomeLauncher(props: {
  state: LauncherState
  projects: PreparedProject[]
  query: string
  home?: string
  refreshing?: boolean
  accessory?: JSX.Element
  onQuery: (query: string) => void
  onOpen: (project: PreparedProject) => void
  onCreate: () => void
  onImport: () => void
  onRetry: () => void
}): JSX.Element {
  const action = () => (
    <div class="home-launcher__actions">
      {props.accessory}
      <button class="home-launcher__button home-launcher__button--primary" type="button" onClick={props.onCreate}>
        <IconPlus size={15} strokeWidth={1.5} />
        Create project
      </button>
      <button class="home-launcher__button" type="button" onClick={props.onImport}>
        <IconFolder size={15} strokeWidth={1.5} />
        Import existing folder
      </button>
    </div>
  )

  return (
    <main class="atlas-scroll home-launcher">
      <div class="home-launcher__frame">
        <section class="home-launcher__intro" aria-labelledby="home-launcher-title">
          <span class="home-launcher__eyebrow">Local workspace</span>
          <h1 id="home-launcher-title">Continue your research</h1>
          <p>Create a project to keep its files, sessions, evidence, and tools in one focused workspace.</p>
        </section>

        <Switch>
          <Match when={props.state === "loading"}>
            <section class="home-launcher__state" role="status" aria-live="polite">
              <span class="home-launcher__spinner" aria-hidden="true" />
              <div>
                <h2>Loading recent projects…</h2>
                <p>Reading project history from your local workspace.</p>
              </div>
            </section>
          </Match>

          <Match when={props.state === "error"}>
            <section class="home-launcher__state home-launcher__state--error" role="alert">
              <div>
                <span class="home-launcher__state-label">Connection unavailable</span>
                <h2>We couldn’t reach your local workspace.</h2>
                <p>Check the selected server, then try the connection again.</p>
              </div>
              <button class="home-launcher__button" type="button" onClick={props.onRetry}>
                Try again
              </button>
            </section>
          </Match>

          <Match when={props.state === "empty"}>
            <section class="home-launcher__state home-launcher__state--empty">
              <div>
                <span class="home-launcher__state-label">No recent projects</span>
                <h2>Start a new research project.</h2>
                <p>Aleph Ciencia creates and manages a local workspace for it.</p>
              </div>
              {action()}
            </section>
          </Match>

          <Match when={props.state === "recent"}>
            <section class="home-launcher__recent" aria-labelledby="recent-projects-title">
              <div class="home-launcher__section-head">
                <div>
                  <div class="home-launcher__section-title">
                    <h2 id="recent-projects-title">Recent projects</h2>
                    <Show when={props.refreshing}>
                      <span class="home-launcher__refresh" role="status">
                        Refreshing…
                      </span>
                    </Show>
                  </div>
                  <p>Return to a project on this server.</p>
                </div>
                {action()}
              </div>

              <div class="home-launcher__search">
                <IconSearch size={15} strokeWidth={1.5} />
                <label class="home-launcher__sr-only" for="home-project-search">
                  Search recent projects
                </label>
                <input
                  id="home-project-search"
                  type="search"
                  value={props.query}
                  placeholder="Search projects"
                  onInput={(event) => props.onQuery(event.currentTarget.value)}
                  onKeyDown={(event) => {
                    if (event.key !== "Escape") return
                    props.onQuery("")
                    event.currentTarget.focus()
                  }}
                />
                <Show when={props.query}>
                  <button type="button" onClick={() => props.onQuery("")}>
                    Clear search
                  </button>
                </Show>
              </div>

              <Show
                when={props.projects.length > 0}
                fallback={
                  <div class="home-launcher__no-results" aria-live="polite">
                    <div>
                      <h3>No projects match “{props.query}”</h3>
                      <p>Clear the search or create a new project.</p>
                    </div>
                    <div class="home-launcher__actions">
                      <button class="home-launcher__button" type="button" onClick={() => props.onQuery("")}>
                        Clear search
                      </button>
                      <button
                        class="home-launcher__button home-launcher__button--primary"
                        type="button"
                        onClick={props.onCreate}
                      >
                        <IconPlus size={15} strokeWidth={1.5} />
                        Create project
                      </button>
                    </div>
                  </div>
                }
              >
                <ul class="home-launcher__projects">
                  <For each={props.projects}>
                    {(project) => (
                      <li>
                        <button
                          class="home-launcher__project"
                          type="button"
                          data-project={project.id}
                          onClick={() => props.onOpen(project)}
                        >
                          <span class="home-launcher__folder" aria-hidden="true">
                            <IconFolder size={17} strokeWidth={1.4} />
                          </span>
                          <span class="home-launcher__project-copy">
                            <strong>{projectName(project)}</strong>
                            <span>{projectHint(project)}</span>
                          </span>
                          <time datetime={DateTime.fromMillis(project.updatedAt).toISO() ?? undefined}>
                            {DateTime.fromMillis(project.updatedAt).toRelative() ?? "Recently"}
                          </time>
                          <span class="home-launcher__arrow" aria-hidden="true">
                            <IconArrowRight size={15} strokeWidth={1.5} />
                          </span>
                        </button>
                      </li>
                    )}
                  </For>
                </ul>
              </Show>
            </section>
          </Match>
        </Switch>
      </div>
    </main>
  )
}
