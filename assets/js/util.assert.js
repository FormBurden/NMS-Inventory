/* NMS-Inventory: util.assert.js */
(() => {
	const NS = (window.NMSI = window.NMSI || {});
	function fail(msg) {
		throw new Error(String(msg || "Assertion failed"));
	}
	function assert(cond, msg) {
		if (!cond) fail(msg);
	}
	NS.assert = assert;
	NS.fail = fail;
})();
  