<div align="center">

[English](README.md) · **Español**

<img src="assets/readme/aleph-app-icon.png" alt="Ícono de la app Aleph" width="128"><img src="assets/readme/cli-logos.svg" alt="Funciona con Claude Code, Grok y Codex" height="128">

# Aleph

### Un solo espacio. Trabajo infinito.

Un espacio de trabajo para macOS que reúne tus modelos de IA, tus herramientas y tus archivos, y los pone a trabajar en espacios especializados y en agentes que armas tú.

[![Descargar para macOS](https://img.shields.io/badge/Descargar-macOS%20·%20Apple%20silicon-1f1b4d?style=for-the-badge&logo=apple&logoColor=white)](https://github.com/josuecuguy1307/Aleph/releases/latest/download/Aleph-macOS-arm64.dmg)

[![Versión 0.1.2](https://img.shields.io/badge/versi%C3%B3n-0.1.2-6d5bd0)](https://github.com/josuecuguy1307/Aleph/releases/tag/v0.1.2)
[![Licencia: Apache-2.0](https://img.shields.io/badge/licencia-Apache--2.0-6d5bd0)](LICENSE)
![Homebrew cask](https://img.shields.io/badge/homebrew-josuecuguy1307%2Ftap%2Faleph-6d5bd0)
![Cualquier modelo](https://img.shields.io/badge/modelos-trae%20el%20tuyo-8a7fd6)
![English · Español](https://img.shields.io/badge/app-English%20·%20Español-8a7fd6)

![Conectores MCP](https://img.shields.io/badge/MCP-conectores-1f1b4d?logo=modelcontextprotocol&logoColor=white)
![CLI: Claude Code](https://img.shields.io/badge/CLI-Claude%20Code-D97757?logo=claude&logoColor=white)
![CLI: Codex](https://img.shields.io/badge/CLI-Codex-10a37f?logo=gnometerminal&logoColor=white)

[Sitio web](https://aleph-site-jade.vercel.app/) &nbsp;·&nbsp;
[Ver el tráiler](#mira-el-tráiler) &nbsp;·&nbsp;
[Instalar](#instalar) &nbsp;·&nbsp;
[Cómo se usa](#cómo-usar-aleph) &nbsp;·&nbsp;
[Primeros pasos (en inglés)](docs/GETTING_STARTED.md)

<img src="assets/readme/hero-workshop.webp" alt="El Cuarto en Aleph: agentes y sus herramientas sobre un tablero isométrico, abierto un nivel hacia adentro para editar un agente" width="900">

<sub>El Cuarto: arma un agente colocando su modelo y sus herramientas en el tablero, y luego entra en él para editarlo. (Interfaz en inglés.)</sub>

</div>

---

## Por qué Aleph

Tu trabajo con IA está desperdigado: una app para el chat, otra para los archivos, una terminal para el agente de línea de comandos, una pestaña por cada servicio. Aleph lo pone todo en **un solo espacio**.

<table>
<tr>
<td width="33%" valign="top">
<h4>🧠 Tus modelos</h4>
Conecta un proveedor por API o un agente de línea de comandos que ya uses, como Claude Code o Codex. Aleph no te ata a un solo proveedor.
</td>
<td width="33%" valign="top">
<h4>🧰 Tus herramientas</h4>
Equipa a tus agentes con conectores y herramientas locales, de a uno y a propósito. Conectar una cosa nunca autoriza las demás.
</td>
<td width="33%" valign="top">
<h4>🗂️ Tu trabajo</h4>
Los archivos y artefactos quedan junto a la conversación que los creó, en espacios pensados para cada tipo de trabajo.
</td>
</tr>
</table>

## Mira el tráiler

https://github.com/user-attachments/assets/ad208351-a6ba-4cf1-8096-6173cb717ee8

<sub>55 segundos. ¿No ves el reproductor? [Descarga el tráiler](assets/readme/aleph-trailer.mp4).</sub>

---

## Un vistazo por dentro

<table>
<tr>
<td colspan="2">
<img src="assets/readme/screen-home.jpg" alt="El inicio de Aleph: un saludo, el tablero y la lista de espacios: La Sala, Oficina, Finanzas, Educación, Ciencia, Diseño y Legal"><br>
<b>Inicio.</b> Entra a un espacio: La Sala para conversar y el trabajo general, o un espacio pensado para un tipo de trabajo.
</td>
</tr>
<tr>
<td width="50%" valign="top">
<img src="assets/readme/screen-science-molecule.jpg" alt="Espacio de Ciencia: visor 3D de moléculas con modos de selección, reinicio de cámara y exportación a PNG"><br>
<b>Ciencia.</b> Los archivos científicos se abren en visores de verdad, como este visor de moléculas con modos de selección y exportación a PNG.
</td>
<td width="50%" valign="top">
<img src="assets/readme/screen-finance-chart.jpg" alt="Espacio de Finanzas: métricas de un backtest sobre un gráfico de velas con medias móviles y volumen"><br>
<b>Finanzas.</b> Métricas del backtest, operaciones y un gráfico de velas de una estrategia, con exportación a CSV.
</td>
</tr>
<tr>
<td width="50%" valign="top">
<img src="assets/readme/screen-design-preview.jpg" alt="Espacio de Diseño: vista previa en vivo de una landing page generada"><br>
<b>Diseño.</b> Describe un diseño y mira cómo toma forma la vista previa de la página al lado del chat.
</td>
<td width="50%" valign="top">
<img src="assets/readme/workspaces-map.png" alt="Ilustración: Ciencia, Educación, Oficina, Finanzas, Legal y Diseño en un mismo espacio de trabajo"><br>
<b>Seis espacios, una sola app.</b> Ciencia, Educación, Oficina, Finanzas, Legal y Diseño se abren dentro de la misma Aleph.
</td>
</tr>
</table>

<sub>Las capturas vienen de una versión de desarrollo de Aleph (septiembre de 2026), en su mayoría con la interfaz en inglés, así que algunos detalles pueden diferir de la versión 0.1.2. La ilustración es un concepto del producto, no una captura.</sub>

---

## Los espacios

| Espacio | Para qué sirve |
|---|---|
| 💬 **La Sala** | Conversaciones y trabajo general con un agente |
| 🛠️ **El Cuarto** | Armar agentes: elegir un modelo, darle un objetivo, equipar sus herramientas |
| 📄 **Oficina** | Documentos, hojas de cálculo y presentaciones |
| 📈 **Finanzas** | Análisis y mercado |
| 🎓 **Educación** | Estudio y aprendizaje |
| 🔬 **Ciencia** | Investigación y evidencia |
| 🎨 **Diseño** | Ideas y creación visual |
| ⚖️ **Legal** | Revisión y documentos |

<sub>En inglés, La Sala es *The Room* y El Cuarto es *The Workshop*.</sub>

---

## Instalar

**macOS · Apple silicon**

1. [Descarga `Aleph-macOS-arm64.dmg`](https://github.com/josuecuguy1307/Aleph/releases/latest/download/Aleph-macOS-arm64.dmg).
2. Abre el DMG.
3. Arrastra **Aleph.app** a **Aplicaciones**.
4. Abre **Aleph** desde Aplicaciones.

O con Homebrew:

```sh
brew install --cask josuecuguy1307/tap/aleph
```

> [!NOTE]
> Aleph 0.1.2 tiene firma ad hoc y **no está notarizada**, así que macOS puede bloquearla la primera vez. Intenta abrirla una vez y luego ve a **Ajustes del Sistema → Privacidad y seguridad → Abrir igualmente** ([instrucciones de Apple](https://support.apple.com/es-es/102445)). Hazlo solo con una descarga de esta versión oficial. Homebrew instala la misma app, con el mismo aviso.

---

## Cómo usar Aleph

| | Paso | Qué haces |
|---|---|---|
| 1 | **Abre Aleph** | Sigue los pasos de configuración y elige tu idioma (English o Español). |
| 2 | **Elige tu modelo** | Conecta un proveedor por API con tus propias credenciales, o elige una CLI instalada y con sesión iniciada, como Claude Code o Codex. |
| 3 | **Empieza en La Sala** | Elige un agente, describe lo que quieres hacer y abre los archivos y artefactos que produce. |
| 4 | **Abre un espacio** | Ciencia, Educación, Oficina, Finanzas, Legal o Diseño, según el trabajo que tengas delante. |
| 5 | **Hazlo tuyo en El Cuarto** | Arma agentes, equipa herramientas y organiza flujos de trabajo a los que puedas volver. |

[Sigue con Primeros pasos (en inglés) →](docs/GETTING_STARTED.md)

---

## Tus modelos. Tus herramientas.

Trae el proveedor que quieras y conecta los servicios que necesita tu trabajo. Los modelos, los agentes de línea de comandos y los conectores son capacidades separadas: conectar uno no autoriza los demás.

| Modelos y proveedores de CLI | Herramientas conectadas |
| --- | --- |
| ![Ilustración de APIs de modelos y proveedores de CLI, incluidos Claude Code y Codex](assets/readme/models-and-cli.png) | ![Ilustración de conectores para comunicación, conocimiento, archivos y flujos de trabajo](assets/readme/connect-tools.png) |

> [!IMPORTANT]
> Aleph **funciona con cualquier modelo**, y lo que puedes usar depende de tu equipo. Los modelos disponibles dependen de los proveedores que tengas instalados, de tus sesiones iniciadas y de tus límites de acceso, y los conectores pueden necesitar instalación, una clave de API u OAuth antes de funcionar. Estas ilustraciones muestran conceptos del producto, no la promesa de que cada integración esté lista. **Onshape es opcional y no está certificado.**

---

## Compilar desde el código

Mira [BUILDING.md](BUILDING.md) (en inglés) para los requisitos, la forma oficial de compilar y las limitaciones actuales de reproducibilidad.

## Código abierto

El código propio de Aleph tiene licencia [Apache-2.0](LICENSE). Los componentes de terceros conservan sus propias licencias; ver [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES).

El **nombre, el logo, la mascota y la marca oficial de Aleph**, incluidas las imágenes del producto de este README, se rigen aparte por [TRADEMARKS.md](TRADEMARKS.md) y no los otorga la Apache-2.0. Los forks pueden contar su origen tal cual es, pero no deben dar a entender que son oficiales ni que cuentan con respaldo. [Origen de las imágenes](assets/readme/README.md).

¿Quieres contribuir? Empieza por [CONTRIBUTING.md](CONTRIBUTING.md).

## Versión actual

**0.1.2** · [instalador para macOS y versión del código](https://github.com/josuecuguy1307/Aleph/releases/tag/v0.1.2)

<details>
<summary>Detalles de la versión para desarrolladores</summary>

La página de la versión separa el instalador para macOS de los recursos del sistema invitado, que son solo para desarrolladores. Ahí también están el kernel invitado exacto, el sistema de archivos raíz y el paquete de código de terceros correspondiente. Los [detalles de esos recursos](deploy/guest/ASSETS.md) y su [cumplimiento de licencias](deploy/guest/COMPLIANCE.md) siguen disponibles para desarrolladores; todavía no se afirma que la imagen invitada pueda regenerarse por completo desde el código. No uses el kernel invitado ni el sistema de archivos raíz como instalador de macOS.

La base de código certificada y el alcance de la instantánea están registrados en [SOURCE_PROVENANCE.json](SOURCE_PROVENANCE.json). Este README es la presentación del producto; la etiqueta inmutable `v0.1.2` conserva la instantánea certificada original.

</details>
