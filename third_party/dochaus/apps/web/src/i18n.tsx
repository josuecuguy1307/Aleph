import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react"
import en from "./locales/en.json"
import es from "./locales/es.json"

export type Language = "en" | "es"

const STORAGE_KEY = "dochaus-language"
const LanguageContext = createContext({
  language: "en" as Language,
  setLanguage: (_language: Language) => {},
  t: (text: string) => text,
})

function requestedLanguage(): Language {
  const params = new URLSearchParams(window.location.search)
  // Session context survives router navigation inside Aleph's iframe, but
  // must not override the user's language when this workspace is standalone.
  const aleph = params.get("aleph_lang") || (window.parent !== window ? window.sessionStorage.getItem("aleph.aleph_lang") : null)
  if (aleph) return aleph.toLowerCase().startsWith("es") ? "es" : "en"
  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === "en" || stored === "es") return stored
  return window.navigator.language.toLowerCase().startsWith("es") ? "es" : "en"
}

function translator(language: Language) {
  if (language === "en") return (text: string) => text
  const dictionary = es as Record<string, string>
  return (text: string) => dictionary[text] || text
}

function translateDocument(t: (text: string) => string, root: Node) {
  if (root.nodeType === Node.TEXT_NODE) {
    const node = root as Text
    if (node.parentElement?.closest(".msg, .docx-render, [data-no-translate]")) return
    const source = node.nodeValue || ""
    const value = source.trim()
    const translated = value ? t(value) : value
    if (translated !== value) node.nodeValue = source.replace(value, translated)
    return
  }
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const nodes: Text[] = []
  while (walker.nextNode()) nodes.push(walker.currentNode as Text)
  for (const node of nodes) {
    if (node.parentElement?.closest(".msg, .docx-render, [data-no-translate]")) continue
    const source = node.nodeValue || ""
    const value = source.trim()
    if (!value) continue
    const translated = t(value)
    if (translated !== value) node.nodeValue = source.replace(value, translated)
  }
  if (!(root instanceof Element) && !(root instanceof Document)) return
  const elements = root instanceof Element ? [root, ...root.querySelectorAll("*")] : [...root.querySelectorAll("*")]
  for (const element of elements) {
    if (element.closest(".msg, .docx-render, [data-no-translate]")) continue
    for (const attribute of ["aria-label", "alt", "placeholder", "title"]) {
      const source = element.getAttribute(attribute)
      if (!source) continue
      const translated = t(source)
      if (translated !== source) element.setAttribute(attribute, translated)
    }
  }
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(requestedLanguage)
  const t = useMemo(() => translator(language), [language])

  useEffect(() => {
    document.documentElement.lang = language
    translateDocument(t, document)
    const observer = new MutationObserver((records) => {
      for (const record of records) {
        if (record.type === "characterData" || record.type === "attributes") {
          translateDocument(t, record.target)
        }
        for (const node of record.addedNodes) translateDocument(t, node)
      }
    })
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["aria-label", "alt", "placeholder", "title"],
    })
    return () => observer.disconnect()
  }, [language, t])

  const setLanguage = (next: Language) => {
    if (next !== "en" && next !== "es") return
    window.localStorage.setItem(STORAGE_KEY, next)
    setLanguageState(next)
    window.location.reload()
  }

  return <LanguageContext.Provider value={{ language, setLanguage, t }}>{children}</LanguageContext.Provider>
}

export function useLanguage() {
  return useContext(LanguageContext)
}

export function localeParity() {
  return {
    missing: Object.keys(en).filter((key) => !(key in es)),
    extra: Object.keys(es).filter((key) => !(key in en)),
  }
}
