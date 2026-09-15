// Injected by the desktop app into the InHire job window (desktop/apply_detection.py).
//
// Watches the page's own requests and reports a successful application submit
// to the window bridge. InHire's job page sends the form with
// POST <api>/job-talents/public/<jobId>/talents (route publicJobApplicationSubmit
// in its bundle). The desktop only accepts the id of the job that window shows.
//
// Rules: idempotent (guard flag), one report per id, and never throw into the page.
(function () {
  "use strict";

  var w = window;
  if (w.__jobWatcherApplyHook) {
    return;
  }
  w.__jobWatcherApplyHook = true;

  var ROUTE = /^\/job-talents\/public\/([A-Za-z0-9-]{1,100})\/talents\/?$/;
  var reported = {};
  var pending = [];

  function pathOf(url) {
    try {
      var text = String(url);
      if (typeof w.URL === "function") {
        var base = w.location && w.location.href ? w.location.href : undefined;
        return new w.URL(text, base).pathname;
      }
      return text.replace(/^[a-z]+:\/\/[^/]+/i, "").split(/[?#]/)[0];
    } catch (error) {
      return "";
    }
  }

  function deliver(id) {
    var api = w.pywebview && w.pywebview.api;
    if (!api || typeof api.report_application !== "function") {
      return false;
    }
    try {
      var result = api.report_application(id);
      if (result && typeof result.then === "function") {
        result.then(null, function () {});
      }
    } catch (error) {
      // The bridge failing must not break the application form.
    }
    return true;
  }

  function flush() {
    var left = [];
    for (var i = 0; i < pending.length; i += 1) {
      if (!deliver(pending[i])) {
        left.push(pending[i]);
      }
    }
    pending = left;
  }

  function report(method, url, status) {
    try {
      if (String(method || "GET").toUpperCase() !== "POST") {
        return;
      }
      var code = Number(status);
      if (!(code >= 200 && code < 300)) {
        return;
      }
      var match = ROUTE.exec(pathOf(url));
      if (!match) {
        return;
      }
      var id = match[1];
      if (reported[id]) {
        return;
      }
      reported[id] = true;
      if (!deliver(id)) {
        pending.push(id);
      }
    } catch (error) {
      // Never throw into the page.
    }
  }

  try {
    if (typeof w.addEventListener === "function") {
      // pywebview exposes the bridge asynchronously on this event.
      w.addEventListener("pywebviewready", flush);
    }
  } catch (error) {
    // Ignore: reports are retried on the next report call.
  }

  try {
    var XHR = w.XMLHttpRequest;
    if (XHR && XHR.prototype) {
      var originalOpen = XHR.prototype.open;
      var originalSend = XHR.prototype.send;
      XHR.prototype.open = function (method, url) {
        try {
          this.__jobWatcherMethod = method;
          this.__jobWatcherUrl = url;
        } catch (error) {
          // Ignore.
        }
        return originalOpen.apply(this, arguments);
      };
      XHR.prototype.send = function () {
        var xhr = this;
        try {
          xhr.addEventListener("loadend", function () {
            report(xhr.__jobWatcherMethod, xhr.__jobWatcherUrl || xhr.responseURL, xhr.status);
          });
        } catch (error) {
          // Ignore.
        }
        return originalSend.apply(this, arguments);
      };
    }
  } catch (error) {
    // Ignore: detection is best effort.
  }

  try {
    if (typeof w.fetch === "function") {
      var originalFetch = w.fetch;
      w.fetch = function (input, init) {
        var method = "GET";
        var url = "";
        try {
          if (input && typeof input === "object" && "url" in input) {
            url = input.url;
            method = input.method || method;
          } else {
            url = String(input);
          }
          if (init && init.method) {
            method = init.method;
          }
        } catch (error) {
          // Ignore.
        }
        var result = originalFetch.apply(this, arguments);
        try {
          if (result && typeof result.then === "function") {
            result.then(
              function (response) {
                report(method, url || (response && response.url), response && response.status);
              },
              function () {}
            );
          }
        } catch (error) {
          // Ignore.
        }
        return result;
      };
    }
  } catch (error) {
    // Ignore: detection is best effort.
  }
})();
