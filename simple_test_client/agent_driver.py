import asyncio
import logging
from signal import SIGINT, SIGTERM
import os
import argparse
import random

import dotenv

from livekit import rtc
from test_script import TestScript
from room_handlers import setup_room_handlers
from room_manager import run_room, cleanup

dotenv.load_dotenv()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish audio to a LiveKit room")
    parser.add_argument("--room", help="Name of the LiveKit room to join")
    parser.add_argument(
        "--test", help="Name of the test to run (without .json extension)"
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.FileHandler("publish_wave.log"), logging.StreamHandler()],
    )

    # Generate random room name if not provided
    room_name = args.room
    if not room_name:
        room_name = f"room_{random.randint(1, 1000)}"
        logging.info(f"Using randomly generated room name: {room_name}")

    logging.info("HIHIH")
    # Create a new event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    room = rtc.Room(loop=loop)
    listener_room = rtc.Room(loop=loop)

    # Load test script if provided
    script = None
    if args.test:
        try:
            script_path = os.path.join("tests", f"{args.test}.json")
            if not os.path.exists(script_path):
                logging.error(f"Test script not found: {script_path}")
                os._exit(1)
            script = TestScript(script_path, room)
            logging.info(f"Loaded test script: {args.test}")
        except Exception as e:
            logging.error(f"Failed to load script: {e}")
            os._exit(1)

    # Set up room handlers
    setup_room_handlers(room, script, play_audio=False)
    setup_room_handlers(listener_room, script, play_audio=True)

    async def run_publisher():
        """Run the publisher participant."""
        try:
            await run_room(room, room_name, script, listener_mode=False)
            logging.info("Publisher connected to room")
            # Keep running until manually terminated
            while True:
                await asyncio.sleep(10)
                logging.info("Publisher still active")
        except asyncio.CancelledError:
            logging.info("Publisher task cancelled")
        except rtc.ConnectError as e:
            logging.error("Connection error in publisher: %s", e)
        except RuntimeError as e:
            logging.error("Runtime error in publisher: %s", e)

    async def run_listener():
        """Run the listener participant."""
        try:
            # Use a different identity for the listener
            await run_room(listener_room, room_name, script, listener_mode=True)
            logging.info("Listener connected to room")
            # Keep running until manually terminated
            while True:
                await asyncio.sleep(10)
                logging.info("Listener still active")
        except asyncio.CancelledError:
            logging.info("Listener task cancelled")
        except rtc.ConnectError as e:
            logging.error("Connection error in listener: %s", e)
        except RuntimeError as e:
            logging.error("Runtime error in listener: %s", e)

    async def main():
        """Main function to run both participants concurrently."""
        try:
            # Run both participants concurrently
            publisher_task = asyncio.create_task(run_publisher())
            await asyncio.sleep(1)
            listener_task = asyncio.create_task(run_listener())
            await asyncio.gather(publisher_task, listener_task)

            # Wait for both tasks to complete (which should be never unless there's an error)
            # await asyncio.gather(listener_task)
        except asyncio.CancelledError:
            logging.info("Main task cancelled")
        except Exception as e:
            import traceback

            logging.error(f"Error in main task: {e}")
            logging.error(f"Exception type: {type(e).__name__}")
            logging.error(f"Stack trace:\n{traceback.format_exc()}")
            # Get detailed exception info
            import sys

            exc_info = sys.exc_info()
            if exc_info[0] is not None:
                logging.error(f"Exception info: {exc_info}")
            # Log all current tasks for debugging
            for i, task in enumerate(asyncio.all_tasks()):
                logging.error(f"Task {i}: {task.get_name()} - {task}")
                if (
                    task.done()
                    and not task.cancelled()
                    and task.exception() is not None
                ):
                    logging.error(f"Task {i} exception: {task.exception()}")
        finally:
            # Clean up both rooms when exiting
            await cleanup(room)
            await cleanup(listener_room)
            os._exit(0)

    # Start the main task
    main_task = asyncio.ensure_future(main())

    # Handle signals
    def signal_handler():
        logging.info("Received signal, shutting down...")
        asyncio.ensure_future(cleanup(room))
        asyncio.ensure_future(cleanup(listener_room))
        main_task.cancel()
        loop.stop()
        os._exit(0)

    for signal in [SIGINT, SIGTERM]:
        loop.add_signal_handler(signal, signal_handler)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info("Received keyboard interrupt")
        asyncio.ensure_future(cleanup(room))
        asyncio.ensure_future(cleanup(listener_room))
        main_task.cancel()
    finally:
        loop.close()
        os._exit(0)
