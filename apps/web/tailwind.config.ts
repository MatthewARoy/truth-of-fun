import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      borderRadius: {
        ui: "var(--ui-radius)",
      },
      colors: {
        brand: {
          100: "#d2f4ff",
          200: "#9ee7ff",
          300: "#6ed8ff",
          400: "#30c2f2",
          500: "#139ec9",
        },
      },
    },
  },
  plugins: [],
};

export default config;
