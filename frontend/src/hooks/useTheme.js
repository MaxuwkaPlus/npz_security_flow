import { useState } from "react";
import { applyTheme, currentTheme } from "../utils/theme.js";

export function useTheme() {
  const [theme, setTheme] = useState(currentTheme);

  const toggleTheme = () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    setTheme(applyTheme(next));
  };

  return { theme, toggleTheme };
}
