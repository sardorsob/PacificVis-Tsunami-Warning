import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { DemoApp } from "./DemoApp";
import { RadialDemo } from "./radial/RadialDemo";
import { EvidencePanel } from "./evidence/EvidencePanel";
import { StoryRoute } from "./story/StoryRoute";
import "./style.css";

const root=document.getElementById("root");
if(!root)throw new Error("Missing demo root.");
createRoot(root).render(<StrictMode><DemoApp radialRenderer={RadialDemo} evidenceRenderer={EvidencePanel} storyRenderer={StoryRoute}/></StrictMode>);
