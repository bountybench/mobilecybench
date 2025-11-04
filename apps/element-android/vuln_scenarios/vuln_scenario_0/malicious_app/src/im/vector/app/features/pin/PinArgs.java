package im.vector.app.features.pin;

import android.os.Parcel;
import android.os.Parcelable;

public class PinArgs implements Parcelable {
    public final PinMode pinMode;

    public PinArgs(PinMode pinMode) {
        this.pinMode = pinMode;
    }

    protected PinArgs(Parcel in) {
        // Match Kotlin's @Parcelize enum serialization - it writes enum name as string
        String enumName = in.readString();
        pinMode = PinMode.valueOf(enumName);
    }

    @Override
    public void writeToParcel(Parcel dest, int flags) {
        // Match Kotlin's @Parcelize enum serialization - write enum name as string
        dest.writeString(pinMode.name());
    }

    @Override
    public int describeContents() {
        return 0;
    }

    public static final Creator<PinArgs> CREATOR = new Creator<PinArgs>() {
        @Override
        public PinArgs createFromParcel(Parcel in) {
            return new PinArgs(in);
        }

        @Override
        public PinArgs[] newArray(int size) {
            return new PinArgs[size];
        }
    };
}