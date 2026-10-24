import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Gallery } from "./Gallery";

createRoot(document.getElementById("sample-root")!).render(<StrictMode><Gallery /></StrictMode>);
