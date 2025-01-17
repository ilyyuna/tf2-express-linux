from multiprocessing import Process, Pool
from time import sleep, time

from express.database import *
from express.settings import *
from express.logging import Log, f
from express.prices import update_pricelist
from express.config import *
from express.client import Client
from express.offer import Offer, valuate
from express.utils import to_refined, refinedify

import socketio


def run(bot: dict) -> None:
    try:
        client = Client(bot)
        client.login()

        log = Log(bot["name"])

        processed = []
        values = {}

        log.info(f"Polling offers every {TIMEOUT} seconds")

        while True:
            log = Log(bot["name"])
            log.debug("Polling offers...")
            offers = client.get_offers()

            for offer in offers:
                offer_id = offer["tradeofferid"]

                if offer_id not in processed:
                    log = Log(bot["name"], offer_id)

                    trade = Offer(offer)
                    steam_id = trade.get_partner()

                    if trade.is_active() and not trade.is_our_offer():
                        log.trade(f"Received a new offer from {f.YELLOW + steam_id}")

                        if trade.is_from_owner():
                            log.trade("Offer is from owner")
                            client.accept(offer_id)

                        elif trade.is_gift() and accept_donations:
                            log.trade("User is trying to give items")
                            client.accept(offer_id)

                        elif trade.is_scam() and decline_scam_offers:
                            log.trade("User is trying to take items")
                            client.decline(offer_id)

                        elif trade.is_valid():
                            log.trade("Processing offer...")

                            their_items = offer["items_to_receive"]
                            our_items = offer["items_to_give"]

                            items = get_items()

                            their_value = valuate(their_items, "buy", items)
                            our_value = valuate(our_items, "sell", items)

                            item_amount = len(their_items) + len(our_items)
                            log.trade(f"Offer contains {item_amount} items")

                            difference = to_refined(their_value - our_value)
                            summary = "User value: {} ref, our value: {} ref, difference: {} ref"

                            log.trade(
                                summary.format(
                                    to_refined(their_value),
                                    to_refined(our_value),
                                    refinedify(difference),
                                )
                            )

                            if their_value >= our_value:
                                values[offer_id] = {
                                    "our_value": to_refined(our_value),
                                    "their_value": to_refined(their_value),
                                }
                                client.accept(offer_id)

                            else:
                                if decline_bad_trade:
                                    client.decline(offer_id)
                                else:
                                    log.trade(
                                        "Ignoring offer as automatic decline is disabled"
                                    )

                        else:
                            log.trade("Offer is invalid")

                    else:
                        log.trade("Offer is not active")

                    processed.append(offer_id)

            del offers

            for offer_id in processed:
                offer = client.get_offer(offer_id)
                trade = Offer(offer)

                log = Log(bot["name"], offer_id)

                if not trade.is_active():
                    state = trade.get_state()
                    log.trade(f"Offer state changed to {f.YELLOW + state}")

                    if trade.is_accepted() and "tradeid" in offer:
                        if save_trades:
                            Log().info("Saving offer data...")

                            if offer_id in values:
                                offer["our_value"] = values[offer_id]["our_value"]
                                offer["their_value"] = values[offer_id]["their_value"]

                            offer["receipt"] = client.get_receipt(offer["tradeid"])
                            add_trade(offer)

                    if offer_id in values:
                        values.pop(offer_id)

                    processed.remove(offer_id)

            sleep(TIMEOUT)

    except BaseException as e:
        log.info(f"Caught {type(e).__name__}")

        try:
            client.logout()
        except:
            pass

        log.info(f"Stopped")


def database() -> None:
    try:
        items_in_database = get_items()
        log = Log()

        while True:
            if not items_in_database == get_items():
                log.info("Item(s) were added or removed from the database")
                items_in_database = get_items()
                update_pricelist(items_in_database)
                log.info("Successfully updated all prices")
            sleep(10)

    except BaseException:
        pass


if __name__ == "__main__":
    t1 = time()
    log = Log()

    try:
        socket = socketio.Client()

        items = get_items()
        update_pricelist(items)
        log.info("Successfully updated all prices")

        del items

        @socket.event
        def connect():
            socket.emit("authentication")
            log.info("Successfully connected to Prices.TF socket server")

        @socket.event
        def authenticated(data):
            pass

        @socket.event
        def price(data):
            if data["name"] in get_items():
                update_price(data["name"], True, data["buy"], data["sell"])

        @socket.event
        def unauthorized(sid):
            pass

        socket.connect("https://api.prices.tf")
        log.info("Listening to Prices.TF for price updates")

        process = Process(target=database)
        process.start()

        with Pool(len(BOTS)) as p:
            p.map(run, BOTS)

    except BaseException as e:
        if e:
            log.error(e)

    finally:
        socket.disconnect()
        process.terminate()
        t2 = time()
        log.info(f"Done. Bot ran for {round(t2-t1, 1)} seconds")
        log.close()
        quit()
