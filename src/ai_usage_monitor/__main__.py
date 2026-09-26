import sys

if __name__ == "__main__":
    if {"--print", "--cli", "--claude-raw"} & set(sys.argv):
        from ai_usage_monitor.cli import main

        sys.exit(main())

    from ai_usage_monitor.app import App

    App().run()
