import React from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import App from "./App"
import "./aleph-fonts.css"
import "./styles.css"
import { LanguageProvider } from "./i18n"

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <LanguageProvider><App /></LanguageProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
