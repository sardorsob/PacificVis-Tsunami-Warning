import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { DemoApp } from "./DemoApp";
import { RadialDemo } from "./radial/RadialDemo";
import "./style.css";

const root=document.getElementById("root");
if(!root)throw new Error("Missing demo root.");
createRoot(root).render(<StrictMode><DemoApp radialRenderer={RadialDemo}/></StrictMode>);
