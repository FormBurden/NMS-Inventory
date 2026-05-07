/* NMS-Inventory: core.dom.js */
(() => {
	const NS = (window.NMSI = window.NMSI || {});
	function el(tag, props = {}, children = []) {
		const e = document.createElement(tag);
		Object.assign(e, props);
		for (const c of (Array.isArray(children) ? children : [children])) {
			if (c != null) e.appendChild(c);
		}
		return e;
	}
	function on(target, type, fn, opts) {
		if (target) target.addEventListener(type, fn, opts);
	}
	NS.el = el;
	NS.on = on;
})();
  