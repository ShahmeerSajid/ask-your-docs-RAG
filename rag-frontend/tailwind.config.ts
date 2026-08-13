import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0F1419",
        panel: "#161C24",
        line: "#26303C",
        brass: "#C9A24B",
        brasssoft: "#8A7638",
        parchment: "#EDE9E0",
        slate: "#8B94A3",
        rust: "#B8543A",
      },
      fontFamily: {
        display: ["var(--font-display)", "serif"],
        body: ["var(--font-body)", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
