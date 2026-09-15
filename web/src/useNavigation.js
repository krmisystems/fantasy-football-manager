import { useEffect, useState } from "react";
import { readRoute, routeHash } from "./navigation.js";

export default function useNavigation() {
  const [route, setRoute] = useState(() => readRoute(window.location.hash));
  useEffect(() => { window.scrollTo(0, 0); }, [route.view, route.team]);
  useEffect(() => {
    const changed = () => setRoute(readRoute(window.location.hash));
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  function navigate(next) {
    const hash = routeHash(next);
    if (window.location.hash !== hash) window.location.hash = hash;
    setRoute(readRoute(hash));
  }
  return [route, navigate];
}
