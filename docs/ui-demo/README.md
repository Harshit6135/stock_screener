# UI layout preview

Open `index.html` in a browser. This standalone demo has no dependencies on the application and uses illustrative data only.

Use the sidebar to preview all nine main screens. Portfolio supports a holding search, position details, risk details, trade journal, and a simulated import flow. The theme button switches between light and dark appearances.

Import guidance appears only in the import dialog, at the source, preparation, and review steps. The dashboard prioritises four metrics, a performance chart, an actionable risk alert, and a short holdings table. Secondary metrics and operational details use disclosure panels.

This is a design proposal; backend workflows and live actions have not been changed. Some demo buttons show explanatory placeholders instead of full workflows.

Research runs now includes all 25 registered job kinds, dynamic forms for common jobs, an advanced JSON editor for complex jobs, and a full-pipeline mode. Submitted parameters are captured in session memory; jobs simulate queued, running, complete, failed, cancelled, and retried states. Pause/start the demo worker to inspect queuing. No request is sent to the app.

Guide now includes all nine tabs with purpose, numbered steps, terminology, prerequisites, and next-action links.

Portfolio now follows the archived dashboard: a six-index carousel, explicit simulated live-feed controls, updates to price/value/P&L, an intraday day-P&L trace, historical equity, and historical drawdown. Start live preview to animate sample ticks; pause, connection-loss/reconnect, and reset controls are included. Historical charts do not change with intraday ticks. This preview does not open a real broker connection.

Job definition guide: `#guide/jobs` lists all registered jobs plus the full pipeline. Research runs links directly to `#guide/job/<kind>` for the selected job. Each definition explains when to use it, prerequisites, individual parameters, a sample payload, expected result, and links back to the selected launcher and result page.

Holdings now shows all eight positions, strategy, opened date, quantity, average cost, latest and previous prices, day P&L, invested amount, market value, unrealised P&L and percentage, trailing/hard stops, risk, stop status, and quote time. The stock column stays pinned while the table scrolls. Incoming demo ticks update rows by symbol, including monetary totals, without recreating rows or losing search/scroll state.
