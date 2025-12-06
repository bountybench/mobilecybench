package im.vector.app.features.pin;

import android.os.Parcel;
import android.os.Parcelable;

public class PinArgs implements Parcelable {
    private final PinMode pinMode;

    public PinArgs(PinMode pinMode) {
        this.pinMode = pinMode;
    }

    protected PinArgs(Parcel in) {
        this.pinMode = PinMode.valueOf(in.readString());
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

    @Override
    public int describeContents() {
        return 0;
    }

    @Override
    public void writeToParcel(Parcel dest, int flags) {
        dest.writeString(pinMode.name());
    }

    public PinMode getPinMode() {
        return pinMode;
    }
}