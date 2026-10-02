import { type ParentComponent } from "solid-js"
import SkillsPage from "@/atlas/SkillsPage"

const STYLE = `
.settings-skills {
  display: flex;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.settings-skills .skills-workspace {
  background: transparent;
}
.settings-skills .skills-workspace__header {
  padding: 16px 24px 12px;
  background: transparent;
}
.settings-skills .skills-workspace__summary {
  margin-bottom: 10px;
}
.settings-skills .skills-workspace__body {
  padding: 0 24px 32px;
}
.settings-skills .skills-workspace__content {
  width: 100%;
  max-width: 820px;
  margin: 0;
}
.settings-skills .skills-workspace__row {
  grid-template-columns: minmax(120px, 0.65fr) minmax(180px, 1.5fr) minmax(80px, 0.6fr) auto;
  gap: 12px;
}
@media (max-width: 760px) {
  .settings-skills .skills-workspace__header {
    padding: 12px 16px 10px;
  }
  .settings-skills .skills-workspace__body {
    padding: 0 16px 28px;
  }
  .settings-skills .skills-workspace__row {
    grid-template-columns: minmax(0, 1fr) auto;
  }
}
`

export const SkillsFrame: ParentComponent = (props) => (
  <section class="settings-skills" aria-label="Skills">
    <style>{STYLE}</style>
    {props.children}
  </section>
)

const Skills = () => (
  <SkillsFrame>
    <SkillsPage embedded />
  </SkillsFrame>
)

export default Skills
