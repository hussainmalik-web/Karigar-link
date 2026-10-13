(() => {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduceMotion || !('IntersectionObserver' in window)) return;

  const roots = [document.querySelector('#content'), document.querySelector('main')].filter(Boolean);
  if (!roots.length) return;

  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.08, rootMargin: '0px 0px -28px 0px' });

  const reveal = root => {
    const elements = root.matches('#content')
      ? [...root.children, ...root.querySelectorAll('.card,.dashboard-hero,.studio-hero,.v2-hero,.marketplace-product,.product-card,.promise,.closing')]
      : [...root.querySelectorAll('.product-card,.promise,.closing,.product-image,.intro,.panel,.kpi')];
    [...new Set(elements)].forEach((element, index) => {
      if (element.classList.contains('scroll-reveal')) return;
      element.classList.add('scroll-reveal');
      element.style.setProperty('--reveal-delay', `${Math.min(index % 6, 5) * 65}ms`);
      observer.observe(element);
    });
  };

  roots.forEach(root => {
    reveal(root);
    new MutationObserver(() => reveal(root)).observe(root, { childList: true, subtree: true });
  });
})();
