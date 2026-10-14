/** Use the same easing for CSS transitions and Web Animations. */
export function motionEasing() {
  return getComputedStyle(document.documentElement).getPropertyValue('--motion-ease-out').trim()
    || 'cubic-bezier(.16,1,.3,1)';
}
