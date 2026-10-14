"""Item templates for the FMCG tenants.

Each category lists generic items with pack variants `label:unit:mrp` and a GST slab. The builder
joins them with fictional brands. Prices are representative for small Indian retail packs. GST
codes follow the representative mapping in `seed-data-spec.md` section 5 (not tax advice).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    name: str
    packs: tuple[str, ...]
    gst: str = "GST5"
    tag: str = ""


def _i(name: str, packs: str, gst: str = "GST5", tag: str = "") -> Item:
    return Item(name, tuple(p.strip() for p in packs.split(";")), gst, tag)


# category slug -> (display name, A count, B count, items)
FMCG_CATEGORIES: dict[str, tuple[str, int, int, tuple[Item, ...]]] = {
    "atta-rice-grains": (
        "Atta, rice and grains",
        8,
        10,
        (
            _i("Chakki Atta", "5 kg:pack:245;10 kg:pack:468;1 kg:pack:56", "GST0"),
            _i("Multigrain Atta", "5 kg:pack:318;1 kg:pack:74", "GST5"),
            _i("Basmati Rice", "1 kg:pack:142;5 kg:pack:655", "GST0"),
            _i("Sona Masoori Rice", "5 kg:pack:365;10 kg:pack:690;25 kg:pack:1340", "GST0"),
            _i("Idli Rice", "5 kg:pack:288;1 kg:pack:64", "GST0"),
            _i("Poha Thick", "500 g:pack:48;1 kg:pack:92", "GST5"),
            _i("Sooji Rava", "500 g:pack:38;1 kg:pack:72", "GST0"),
            _i("Maida", "500 g:pack:29;1 kg:pack:54", "GST0"),
            _i("Besan", "500 g:pack:74;1 kg:pack:138", "GST0"),
            _i("Jowar Atta", "1 kg:pack:66", "GST0"),
            _i("Bajra Atta", "1 kg:pack:60", "GST0"),
            _i("Ragi Flour", "500 g:pack:72", "GST5"),
            _i("Daliya Broken Wheat", "500 g:pack:54", "GST0"),
            _i("Rice Flour", "1 kg:pack:64", "GST0"),
        ),
    ),
    "pulses-dal": (
        "Pulses and dal",
        7,
        8,
        (
            _i("Toor Dal", "500 g:pack:96;1 kg:pack:182", "GST0"),
            _i("Moong Dal Yellow", "500 g:pack:84;1 kg:pack:158", "GST0"),
            _i("Chana Dal", "500 g:pack:62;1 kg:pack:118", "GST0"),
            _i("Urad Dal Split", "500 g:pack:88;1 kg:pack:166", "GST0"),
            _i("Masoor Dal", "500 g:pack:70;1 kg:pack:132", "GST0"),
            _i("Kabuli Chana", "500 g:pack:76;1 kg:pack:146", "GST0"),
            _i("Rajma", "500 g:pack:98;1 kg:pack:188", "GST0"),
            _i("Green Moong Whole", "500 g:pack:82;1 kg:pack:154", "GST0"),
            _i("Black Chana", "500 g:pack:58;1 kg:pack:110", "GST0"),
            _i("Matki Moth Beans", "500 g:pack:72", "GST0"),
        ),
    ),
    "edible-oils-ghee": (
        "Edible oils and ghee",
        5,
        7,
        (
            _i("Sunflower Oil", "1 l:pouch:158;5 l:tin:765;500 ml:pouch:84", "GST5", "oil"),
            _i("Groundnut Oil", "1 l:bottle:224;5 l:tin:1090;500 ml:bottle:120", "GST5", "oil"),
            _i("Mustard Oil", "1 l:bottle:178;5 l:tin:860;500 ml:bottle:94", "GST5", "oil"),
            _i("Soybean Oil", "1 l:pouch:142;5 l:tin:690", "GST5", "oil"),
            _i("Refined Rice Bran Oil", "1 l:pouch:172;5 l:tin:830", "GST5", "oil"),
            _i("Cow Ghee", "500 ml:bottle:365;1 l:bottle:715;200 ml:bottle:162", "GST5", "ghee"),
            _i("Vanaspati", "1 kg:pack:168;500 g:pack:92", "GST5", "oil"),
            _i("Sesame Oil", "500 ml:bottle:238;1 l:bottle:455", "GST5", "oil"),
        ),
    ),
    "sugar-salt-jaggery": (
        "Sugar, salt and jaggery",
        4,
        5,
        (
            _i("Sugar", "1 kg:pack:48;5 kg:pack:236", "GST5", "sugar"),
            _i("Iodised Salt", "1 kg:pack:26;500 g:pack:14", "GST0", "salt"),
            _i("Jaggery Block", "500 g:pack:46;1 kg:pack:88", "GST0", "jaggery"),
            _i("Rock Salt", "500 g:pack:38", "GST0", "salt"),
            _i("Sugar Cubes", "500 g:pack:62", "GST5", "sugar"),
            _i("Brown Sugar", "500 g:pack:58", "GST5", "sugar"),
            _i("Jaggery Powder", "500 g:pack:64", "GST0", "jaggery"),
        ),
    ),
    "spices-masalas": (
        "Spices and masalas",
        7,
        9,
        (
            _i("Turmeric Powder", "100 g:pack:38;200 g:pack:72", "GST5"),
            _i("Red Chilli Powder", "100 g:pack:44;200 g:pack:82;500 g:pack:190", "GST5"),
            _i("Coriander Powder", "100 g:pack:32;200 g:pack:60", "GST5"),
            _i("Cumin Seeds", "100 g:pack:54;200 g:pack:104", "GST5"),
            _i("Garam Masala", "50 g:pack:48;100 g:pack:92", "GST5"),
            _i("Goda Masala", "100 g:pack:62;200 g:pack:118", "GST5"),
            _i("Pav Bhaji Masala", "50 g:pack:42;100 g:pack:78", "GST5"),
            _i("Mustard Seeds", "100 g:pack:26;200 g:pack:48", "GST5"),
            _i("Black Pepper", "50 g:pack:68;100 g:pack:128", "GST5"),
            _i("Kashmiri Chilli Powder", "100 g:pack:84", "GST5"),
            _i("Chaat Masala", "50 g:pack:36", "GST5"),
            _i("Sambar Masala", "100 g:pack:58", "GST5"),
        ),
    ),
    "tea-coffee": (
        "Tea and coffee",
        4,
        6,
        (
            _i("Tea Dust Strong", "250 g:pack:118;500 g:pack:228;1 kg:pack:440", "GST5"),
            _i("Premium Leaf Tea", "250 g:pack:168;500 g:pack:325", "GST5"),
            _i("Masala Tea", "250 g:pack:152", "GST5"),
            _i("Green Tea Bags", "25 bags:box:148;100 bags:box:520", "GST5"),
            _i("Instant Coffee", "50 g:bottle:168;100 g:bottle:310", "GST5"),
            _i("Filter Coffee Blend", "200 g:pack:178;500 g:pack:410", "GST5"),
            _i("Ginger Tea Premix", "10 sachets:box:98", "GST5"),
        ),
    ),
    "biscuits-cookies": (
        "Biscuits and cookies",
        7,
        9,
        (
            _i("Glucose Biscuits", "100 g:pack:10;250 g:pack:30;800 g:pack:90", "GST18"),
            _i("Marie Biscuits", "150 g:pack:25;250 g:pack:42", "GST18"),
            _i("Cream Biscuits", "100 g:pack:20;200 g:pack:40", "GST18"),
            _i("Butter Cookies", "150 g:pack:60;300 g:pack:115", "GST18"),
            _i("Digestive Biscuits", "250 g:pack:86;500 g:pack:160", "GST18"),
            _i("Chocolate Cream Biscuits", "100 g:pack:25;250 g:pack:55", "GST18"),
            _i("Salted Crackers", "100 g:pack:20;200 g:pack:38", "GST18"),
            _i("Oat Cookies", "150 g:pack:70", "GST18"),
            _i("Jeera Biscuits", "100 g:pack:20;200 g:pack:36", "GST18"),
            _i("Coconut Cookies", "200 g:pack:48", "GST18"),
            _i("Milk Rusk", "200 g:pack:42;400 g:pack:78", "GST18"),
        ),
    ),
    "namkeen-snacks": (
        "Namkeen and snacks",
        6,
        7,
        (
            _i("Aloo Bhujia", "40 g:pack:10;200 g:pack:55;400 g:pack:105", "GST5"),
            _i("Moong Dal Namkeen", "40 g:pack:10;200 g:pack:60", "GST5"),
            _i("Potato Chips Salted", "30 g:pack:10;52 g:pack:20;100 g:pack:40", "GST5"),
            _i("Masala Peanuts", "40 g:pack:10;200 g:pack:52", "GST5"),
            _i("Chakli", "200 g:pack:68", "GST5"),
            _i("Farsan Mix", "200 g:pack:62;400 g:pack:118", "GST5"),
            _i("Corn Puffs", "30 g:pack:10;60 g:pack:20", "GST5"),
            _i("Banana Chips", "100 g:pack:42;200 g:pack:80", "GST5"),
            _i("Bhel Mix", "150 g:pack:35", "GST5"),
        ),
    ),
    "chocolates-sweets": (
        "Chocolates and sweets",
        4,
        6,
        (
            _i("Milk Chocolate Bar", "13 g:pcs:10;40 g:pcs:40;130 g:pcs:140", "GST18", "choco"),
            _i("Dark Chocolate", "50 g:pcs:90;100 g:pcs:170", "GST18", "choco"),
            _i("Toffee Jar", "100 pcs:box:120;50 pcs:box:70", "GST18", "candy"),
            _i("Gift Chocolate Box", "250 g:box:340;120 g:box:180", "GST18", "choco"),
            _i("Soan Papdi", "250 g:box:130;500 g:box:245", "GST5", "mithai"),
            _i("Kaju Katli Box", "250 g:box:420;500 g:box:820", "GST5", "mithai"),
            _i("Peda Pack", "250 g:box:190", "GST5", "mithai"),
            _i("Fruit Gums", "50 g:pack:20;150 g:pack:55", "GST18", "candy"),
        ),
    ),
    "dry-fruits": (
        "Dry fruits",
        4,
        6,
        (
            _i("Almonds", "200 g:pack:240;500 g:pack:580;1 kg:pack:1120", "GST5"),
            _i("Cashew Whole", "200 g:pack:210;500 g:pack:510", "GST5"),
            _i("Raisins", "200 g:pack:110;500 g:pack:260", "GST5"),
            _i("Walnut Kernels", "200 g:pack:290;500 g:pack:690", "GST5"),
            _i("Pistachios", "200 g:pack:420;500 g:pack:1000", "GST5"),
            _i("Dates Seedless", "500 g:pack:180;1 kg:pack:340", "GST5"),
            _i("Figs Dried", "200 g:pack:260", "GST5"),
            _i("Mixed Dry Fruits", "250 g:pack:320;500 g:pack:620", "GST5"),
        ),
    ),
    "beverages": (
        "Beverages",
        6,
        8,
        (
            _i(
                "Packaged Drinking Water",
                "1 l:bottle:20;500 ml:bottle:10;20 l:jar:80",
                "GST18",
                "water",
            ),
            _i(
                "Cola Soft Drink",
                "600 ml:bottle:40;2 l:bottle:95;250 ml:bottle:20",
                "GST40",
                "soda",
            ),
            _i("Lemon Soda Drink", "600 ml:bottle:40;2 l:bottle:95", "GST40", "soda"),
            _i("Orange Fruit Drink", "200 ml:pack:10;1 l:pack:95", "GST18", "juice"),
            _i("Mango Drink", "200 ml:pack:10;600 ml:bottle:40;1 l:pack:90", "GST18", "juice"),
            _i("Mixed Fruit Juice", "1 l:pack:120;200 ml:pack:25", "GST5", "juice"),
            _i("Coconut Water", "200 ml:pack:40;1 l:pack:160", "GST5", "juice"),
            _i("Energy Drink", "250 ml:pcs:110", "GST40", "soda"),
            _i("Buttermilk Spiced", "200 ml:pack:15", "GST5", "juice"),
            _i("Rose Syrup", "750 ml:bottle:150", "GST18", "juice"),
            _i("Iced Tea Peach", "250 ml:pack:30;500 ml:bottle:60", "GST18", "juice"),
        ),
    ),
    "packaged-foods": (
        "Packaged foods",
        6,
        8,
        (
            _i("Instant Noodles", "70 g:pack:14;280 g:pack:56;560 g:pack:108", "GST5", "noodles"),
            _i("Masala Oats", "40 g:pack:20;200 g:pack:70", "GST5", "cereal"),
            _i("Corn Flakes", "250 g:pack:98;475 g:pack:180", "GST18", "cereal"),
            _i("Tomato Ketchup", "200 g:bottle:60;500 g:bottle:128", "GST5", "sauce"),
            _i("Pasta Penne", "200 g:pack:48;500 g:pack:110", "GST5", "noodles"),
            _i("Ready Poha Mix", "180 g:pack:60", "GST5", "mix"),
            _i("Idli Dosa Batter Mix", "200 g:pack:58;500 g:pack:118", "GST5", "mix"),
            _i("Mixed Fruit Jam", "200 g:bottle:78;500 g:bottle:165", "GST5", "sauce"),
            _i("Peanut Butter", "340 g:bottle:190;1 kg:bottle:480", "GST5", "sauce"),
            _i("Pickle Mango", "200 g:bottle:70;500 g:bottle:150", "GST5", "sauce"),
        ),
    ),
    "dairy-eggs": (
        "Dairy and eggs (packaged)",
        3,
        5,
        (
            _i("UHT Milk Full Cream", "1 l:pack:78;500 ml:pack:42", "GST0", "milk"),
            _i("Salted Butter", "100 g:pack:62;500 g:pack:300", "GST5", "butter"),
            _i("Paneer Packaged", "200 g:pack:90;500 g:pack:215", "GST0", "paneer"),
            _i("Cheese Slices", "200 g:pack:150;10 slices:pack:85", "GST5", "cheese"),
            _i("Flavoured Milk", "200 ml:pack:30", "GST5", "milk"),
            _i("Curd Cup", "400 g:pack:42", "GST0", "paneer"),
        ),
    ),
    "personal-care": (
        "Personal care",
        8,
        9,
        (
            _i("Bath Soap", "100 g:pcs:38;125 g:pcs:48;4 x 100 g:pack:140", "GST5"),
            _i(
                "Shampoo Sachet Strip",
                "10 ml x 12:strip:36;80 ml:bottle:68;340 ml:bottle:260",
                "GST18",
            ),
            _i("Toothpaste", "100 g:tube:68;200 g:tube:128", "GST5"),
            _i("Toothbrush Medium", "1 pc:pcs:30;3 pc:pack:80", "GST5"),
            _i("Hair Oil", "100 ml:bottle:58;200 ml:bottle:105;500 ml:bottle:240", "GST5"),
            _i("Face Cream", "50 g:tube:120;100 g:tube:210", "GST18"),
            _i("Body Lotion", "200 ml:bottle:190;400 ml:bottle:340", "GST18"),
            _i("Talcum Powder", "100 g:pack:62;300 g:pack:160", "GST18"),
            _i("Deodorant Spray", "150 ml:bottle:180", "GST18"),
            _i("Shaving Foam", "200 g:bottle:150", "GST18"),
            _i("Razor Pack", "5 pcs:pack:70", "GST18"),
            _i("Hand Wash Refill", "750 ml:pack:99", "GST18"),
        ),
    ),
    "home-care": (
        "Home care",
        6,
        8,
        (
            _i("Detergent Powder", "1 kg:pack:110;2 kg:pack:210;4 kg:pack:395", "GST18"),
            _i("Liquid Detergent", "1 l:bottle:225;2 l:pack:420", "GST18"),
            _i("Dishwash Bar", "250 g:pcs:20;500 g:pcs:38", "GST18"),
            _i("Dishwash Liquid", "500 ml:bottle:105;1 l:bottle:190", "GST18"),
            _i("Floor Cleaner", "500 ml:bottle:98;1 l:bottle:175", "GST18"),
            _i("Toilet Cleaner", "500 ml:bottle:92;1 l:bottle:170", "GST18"),
            _i("Phenyl", "500 ml:bottle:60;1 l:bottle:110", "GST18"),
            _i("Scrub Pad", "3 pcs:pack:30", "GST18"),
            _i("Garbage Bags", "30 pcs:pack:90", "GST18"),
            _i("Mosquito Coil", "10 coils:box:55", "GST18"),
        ),
    ),
    "festival-puja": (
        "Festival and puja items",
        4,
        5,
        (
            _i(
                "Agarbatti", "20 sticks:box:25;100 sticks:box:90;250 sticks:box:210", "GST5", "puja"
            ),
            _i("Camphor Tablets", "40 g:pack:60;100 g:pack:130", "GST5", "puja"),
            _i("Clay Diya Set", "12 pcs:pack:60;24 pcs:pack:110", "GST5", "diya"),
            _i("Rangoli Colour", "100 g:pack:25;500 g:pack:95", "GST5", "diya"),
            _i("Puja Oil", "500 ml:bottle:130", "GST5", "puja"),
            _i("Cotton Wicks", "100 pcs:pack:20", "GST5", "puja"),
            _i("Kumkum Haldi Set", "1 set:pack:45", "GST5", "puja"),
        ),
    ),
    "baby-misc": (
        "Baby and misc",
        3,
        2,
        (
            _i("Baby Diapers Medium", "20 pcs:pack:299;56 pcs:pack:780", "GST5"),
            _i("Notebook Ruled", "172 pages:pcs:48;300 pages:pcs:84", "GST5"),
            _i("Ball Pen Blue", "10 pcs:pack:50", "GST5"),
            _i("Baby Wipes", "72 pcs:pack:185", "GST18"),
            _i("Matchbox Pack", "10 boxes:pack:20", "GST18"),
        ),
    ),
}
