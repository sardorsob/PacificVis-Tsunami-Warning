import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { DemoApp } from "./DemoApp";
import { EvidencePanel } from "./evidence/EvidencePanel";
import "./style.css";

const root=document.getElementById("root");
if(!root)throw new Error("Missing demo root.");
createRoot(root).render(<StrictMode><DemoApp evidenceRenderer={EvidencePanel}/></StrictMode>);
