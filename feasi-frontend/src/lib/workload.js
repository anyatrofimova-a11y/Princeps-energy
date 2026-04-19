// Re-export shim — actual implementation lives in workload.jsx (moved
// there because the file contains JSX). Existing extensionless imports
// resolve here; Vite's default extension order then finds .jsx cleanly.
export * from "./workload.jsx";
