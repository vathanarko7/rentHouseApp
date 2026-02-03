(function () {
  var chartSection = document.querySelector("details");
  var fieldsets = document.querySelectorAll("fieldset.module");
  if (!chartSection || !fieldsets.length) return;
  var firstFieldset = fieldsets[0];
  firstFieldset.parentNode.insertBefore(chartSection, firstFieldset);
})();
