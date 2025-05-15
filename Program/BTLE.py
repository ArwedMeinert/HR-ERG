from bleak import BleakScanner, BleakClient
import asyncio

class BTLEDeviceConnector:
    HEART_RATE_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
    CYCLING_POWER_CONTROL_UUID = "00002ad9-0000-1000-8000-00805f9b34fb"
    CYCLING_POWER_MEASUREMENT_UUID = "00002a63-0000-1000-8000-00805f9b34fb"
    FTMS_CTRL = "00002ad9-0000-1000-8000-00805f9b34fb"


    async def device_has_characteristic(self, address, uuid):
        try:
            async with BleakClient(address) as client:
                services =  client.services()
                return any(
                    char.uuid.lower() == uuid.lower()
                    for service in services
                    for char in service.characteristics
                )
        except Exception as e:
            print(f"Error checking device {address}: {e}")
            return False

    async def discover_devices_with_characteristic(self, uuid):
        # on platforms that support it, BleakScanner can filter at scan‑time:
        try:
            from bleak.backends.winrt.util import allow_sta
            allow_sta()       # tell Bleak “OK, GUI has its own message loop”
        except ImportError:
            pass
        print("Scanning for BLE devices (advertisement filter)…")
        # first, try to only get devices advertising the service
        devices = await BleakScanner.discover(timeout=5)
        print(f"Advertisement filter found {len(devices)} candidates.")
        return devices
        # now verify by opening a connection (in parallel)
        sem = asyncio.Semaphore(8)
        async def verify(device):
            async with sem:
                try:
                    async with BleakClient(device.address) as client:
                        services = await client.get_services()
                        if any(c.uuid.lower() == uuid.lower()
                            for s in services for c in s.characteristics):
                            return device
                except Exception:
                    return None

        tasks = [asyncio.create_task(verify(d)) for d in devices]
        results = await asyncio.gather(*tasks)
        found = [d for d in results if d]
        print(f"{len(found)} devices confirmed with UUID {uuid}")
        return found


    async def connect(self, address, callback=None):
        client = BleakClient(address)
        try:
            await client.connect()
            print(f"Connected to {address}")
            if callback:
                await callback(client)
            return client
        except Exception as e:
            print(f"Failed to connect to {address}: {e}")
            return None

